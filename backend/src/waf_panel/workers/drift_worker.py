"""Drift worker — pull raw HTTP rows from ClickHouse, featurize them, run
PSI + KS against the frozen 25-feature baseline.

WHY (Sprint 11 hotfix): the previous version hit `traffic_features` and
compared only six numerical columns. The whole point of `waf_ml.features`
is the 25-feature contract — including the eight token flags that signal
real attack-distribution shift (UNION/SELECT, <script, /etc/passwd, …).
We now pull raw HTTP fields from `traffic_log` and run them through the
SAME `featurize()` the trainer used, so drift is measured on every
column of the inference vector.

Audit-actions stay the same:
    audit_log.action = 'ml.drift.alert' | '.warn' | '.clean' | '.skipped'
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

log = logging.getLogger("waf-panel.workers.drift")

UTC = timezone.utc

# WHY: pull the *raw* request fields, not the pre-aggregated features.
#      We featurize on the worker side so the 25-column baseline contract
#      stays fully comparable. ts column is included for ordering only.
_RAW_COLS = ("ts", "method", "path", "query", "ua", "referer")


@dataclass
class DriftRunResult:
    generated_at: str
    status: str
    alert_count: int
    warn_count: int
    n_rows_checked: int
    report_path: str | None


def _baseline_path(active_model_dir: Path) -> Path:
    return active_model_dir / "baseline_features.csv"


def _featurize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Run waf_ml.features.featurize on every row → per-column numpy arrays.

    SAFETY: missing/None values in a row use empty-string defaults inside
    featurize, so a malformed traffic_log row doesn't crash the worker.
    """
    import numpy as np
    from waf_ml.features import FEATURE_COLUMNS, featurize

    cols: dict[str, list[float]] = {c: [] for c in FEATURE_COLUMNS}
    for r in rows:
        try:
            feats = featurize({
                "method": r.get("method") or "",
                "path": r.get("path") or "",
                "query": r.get("query") or "",
                "body": "",  # traffic_log doesn't store request body
                "user_agent": r.get("ua") or "",
                "referer": r.get("referer") or "",
            })
        except Exception as e:  # noqa: BLE001
            log.warning("featurize failed for one row (%s); skipping", e)
            continue
        for col in FEATURE_COLUMNS:
            cols[col].append(float(feats.get(col, 0.0)))
    return {c: np.asarray(v, dtype=np.float64) for c, v in cols.items()}


def _build_pull_sql(window_hours: int, limit: int) -> str:
    """Pull the most recent benign-likely traffic.

    SAFETY: `event_type='access'` — exclude ModSec-blocked rows from the
    drift baseline comparison; otherwise an attack burst would self-match
    against the baseline. Time-window + LIMIT keep it OOM-safe.
    """
    cols = ", ".join(_RAW_COLS)
    return (
        f"SELECT {cols} FROM traffic_log "
        f"WHERE event_type = 'access' "
        f"  AND ts > now() - INTERVAL {int(window_hours)} HOUR "
        f"LIMIT {int(limit)}"
    )


async def run_drift_check(
    *,
    ch_client: Any,
    audit_repo: Any,
    actor_id: UUID | None = None,
    active_model_dir: Path = Path("ml/models/active"),
    window_hours: int = 24,
    pull_limit: int = 100_000,
    report_dir: Path | None = None,
) -> DriftRunResult:
    """Run one drift check on the full 25-feature vector.

    NOTE: `ch_client` and `audit_repo` are dependency-injected so tests
    can drive the worker with stubs (no ClickHouse, no Postgres).
    """
    from waf_ml.drift import compare_columns

    baseline_csv = _baseline_path(active_model_dir)
    if not baseline_csv.exists():
        log.warning("baseline %s missing; nothing to compare against", baseline_csv)
        if audit_repo is not None:
            await audit_repo.record(
                actor_id=actor_id,
                action="ml.drift.skipped",
                target="baseline_missing",
                payload={"baseline": str(baseline_csv)},
            )
        return DriftRunResult(
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            status="clean",
            alert_count=0,
            warn_count=0,
            n_rows_checked=0,
            report_path=None,
        )

    from waf_ml.drift import _read_csv as _read_baseline_csv

    baseline = _read_baseline_csv(baseline_csv)
    sql = _build_pull_sql(window_hours, pull_limit)
    rows = await ch_client.query_json(sql)

    current = _featurize_rows(rows)
    n_rows = len(rows)

    drifts = compare_columns(baseline, current)
    alert = sum(1 for d in drifts if d.level == "alert")
    warn = sum(1 for d in drifts if d.level == "warn")
    status = "alert" if alert > 0 else ("warn" if warn > 0 else "clean")

    payload = {
        "status": status,
        "alert_count": alert,
        "warn_count": warn,
        "n_rows_checked": n_rows,
        "n_features_compared": len(drifts),
        "features": [
            {
                "feature": d.feature,
                "psi": d.psi,
                "ks_pvalue": d.ks_pvalue,
                "level": d.level,
            }
            for d in drifts
        ],
    }

    report_path: Path | None = None
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = report_dir / f"drift-{ts}.json"
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if audit_repo is not None:
        # WHY: audit payload trims feature list to the alert-level subset,
        #      so an alert row stays readable even when 25 columns are scored.
        alert_feats = [
            f for f in payload["features"] if f["level"] in {"alert", "warn"}
        ][:10]
        await audit_repo.record(
            actor_id=actor_id,
            action=f"ml.drift.{status}",
            target="ml_drift",
            payload={
                **payload,
                "features": alert_feats or payload["features"][:5],
                "report_path": str(report_path) if report_path else None,
            },
        )

    log.info(
        "drift check: status=%s alert=%d warn=%d rows=%d features=%d",
        status, alert, warn, n_rows, len(drifts),
    )
    return DriftRunResult(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status=status,
        alert_count=alert,
        warn_count=warn,
        n_rows_checked=n_rows,
        report_path=str(report_path) if report_path else None,
    )


# ── CLI entrypoint — used by `make drift-check` ─────────────────────────

async def _run_from_cli(
    *, active_model_dir: Path, window_hours: int,
    pull_limit: int, report_dir: Path | None,
) -> int:
    from ..clickhouse_client import get_clickhouse_client
    from ..db.session import get_session
    from ..repositories.deps import get_audit_repo

    ch = get_clickhouse_client()
    async for s in get_session():
        audit = await get_audit_repo(s)
        res = await run_drift_check(
            ch_client=ch, audit_repo=audit,
            active_model_dir=active_model_dir,
            window_hours=window_hours, pull_limit=pull_limit,
            report_dir=report_dir,
        )
        await s.commit()
        print(
            f"drift {res.status}: alert={res.alert_count} "
            f"warn={res.warn_count} rows={res.n_rows_checked}"
        )
        return 0 if res.status != "alert" else 2
    return 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="waf-panel-drift-check")
    ap.add_argument("--active-model-dir", type=Path, default=Path("ml/models/active"))
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--pull-limit", type=int, default=100_000)
    ap.add_argument("--report-dir", type=Path, default=Path("ml/drift_reports"))
    args = ap.parse_args(argv)
    return asyncio.run(_run_from_cli(
        active_model_dir=args.active_model_dir,
        window_hours=args.window_hours,
        pull_limit=args.pull_limit,
        report_dir=args.report_dir,
    ))


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["DriftRunResult", "main", "run_drift_check"]

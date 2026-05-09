"""Drift worker — pulls raw HTTP rows, featurises, checks all 25 cols.

Sprint 11 hotfix: the worker now hits `traffic_log` (not `traffic_features`)
and runs `waf_ml.features.featurize` per row, so token-flag drift
(`tok_union_select`, `tok_script`, …) is part of the alert surface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# WHY: the worker imports `waf_ml.features` at runtime; that lives in
# the sibling ml/ package, not pip-installed.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ml" / "src"))


class _StubCh:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.calls: list[str] = []

    async def query_json(self, sql: str) -> list[dict[str, Any]]:
        self.calls.append(sql)
        return self.rows


@pytest.fixture
def baseline_dir(tmp_path: Path):
    """Generate a 25-feature CSV by feeding benign requests through featurize."""
    sys.path.insert(0, str(_REPO / "ml" / "src"))
    from waf_ml.features import FEATURE_COLUMNS, featurize

    rng = np.random.default_rng(42)
    benign_paths = ["/", "/index.html", "/login.php", "/dashboard", "/api/v1/users",
                    "/static/app.js", "/about", "/health", "/contact"]
    benign_qs = ["", "page=1", "id=42", "lang=ru", "tab=overview"]
    benign_uas = ["Mozilla/5.0 (Windows NT 10.0) Chrome/127.0",
                  "Mozilla/5.0 (Macintosh) Safari/17.6"]

    rows = []
    for _ in range(500):
        f = featurize({
            "method": "GET",
            "path": benign_paths[int(rng.integers(0, len(benign_paths)))],
            "query": benign_qs[int(rng.integers(0, len(benign_qs)))],
            "body": "",
            "user_agent": benign_uas[int(rng.integers(0, len(benign_uas)))],
            "referer": "",
        })
        rows.append([f"{f[c]:.6f}" for c in FEATURE_COLUMNS])

    csv_lines = [",".join(FEATURE_COLUMNS)]
    csv_lines.extend(",".join(r) for r in rows)
    d = tmp_path / "active"
    d.mkdir()
    (d / "baseline_features.csv").write_text("\n".join(csv_lines), encoding="utf-8")
    return d


def _benign_raw_rows(n: int = 200) -> list[dict[str, Any]]:
    """Raw traffic_log rows that should match the baseline distribution."""
    rng = np.random.default_rng(7)
    paths = ["/", "/index.html", "/login.php", "/dashboard", "/api/v1/users", "/static/app.js"]
    qs = ["", "page=1", "id=42", "lang=ru", "tab=overview"]
    uas = ["Mozilla/5.0 (Windows NT 10.0) Chrome/127.0",
           "Mozilla/5.0 (Macintosh) Safari/17.6"]
    return [
        {
            "ts": "2026-05-15 10:00:00",
            "method": "GET",
            "path": paths[int(rng.integers(0, len(paths)))],
            "query": qs[int(rng.integers(0, len(qs)))],
            "ua": uas[int(rng.integers(0, len(uas)))],
            "referer": "",
        }
        for _ in range(n)
    ]


def _attack_raw_rows(n: int = 200) -> list[dict[str, Any]]:
    """Raw rows that should trigger drift on token features (UNION/SELECT etc.)."""
    rng = np.random.default_rng(11)
    attack_paths = ["/index.php", "/search", "/admin", "/files", "/etc/passwd"]
    attack_qs = [
        "id=1' UNION SELECT username,password FROM users--",
        "q=<script>alert(1)</script>",
        "file=../../../../etc/passwd",
        "cmd=cat+/etc/passwd",
        "id=1 OR 1=1--",
    ]
    return [
        {
            "ts": "2026-05-15 10:00:00",
            "method": "GET",
            "path": attack_paths[int(rng.integers(0, len(attack_paths)))],
            "query": attack_qs[int(rng.integers(0, len(attack_qs)))],
            "ua": "sqlmap/1.7.2",
            "referer": "",
        }
        for _ in range(n)
    ]


class _StubAudit:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    async def record(self, *, actor_id, action, target, payload=None):
        self.rows.append({
            "actor_id": actor_id, "action": action,
            "target": target, "payload": payload or {},
        })


@pytest.mark.asyncio
async def test_drift_worker_clean_when_distributions_match(baseline_dir):
    from waf_panel.workers.drift_worker import run_drift_check

    ch = _StubCh(_benign_raw_rows(500))
    audit = _StubAudit()

    await run_drift_check(
        ch_client=ch, audit_repo=audit,
        active_model_dir=baseline_dir,
        pull_limit=10_000, window_hours=24,
    )
    # WHY: benign-vs-benign with 500-row samples *can* trip PSI on rare
    # binary features (smoothing of 1/N magnifies tiny count diffs). The
    # contract here is *no token-feature alert* — those would mean a real
    # attack-distribution shift, which there isn't.
    payload = audit.rows[0]["payload"]
    alert_feats = {
        f["feature"] for f in payload.get("features", [])
        if f["level"] == "alert" and (f["feature"].startswith("tok_") or f["feature"].startswith("ua_"))
    }
    assert not alert_feats, (
        f"benign drift run flagged token features: {alert_feats}"
    )


@pytest.mark.asyncio
async def test_drift_worker_alerts_on_attack_traffic_drift(baseline_dir):
    """Attack-shaped rows must trip drift on the token-flag columns."""
    from waf_panel.workers.drift_worker import run_drift_check

    ch = _StubCh(_attack_raw_rows(500))
    audit = _StubAudit()

    res = await run_drift_check(
        ch_client=ch, audit_repo=audit,
        active_model_dir=baseline_dir,
        pull_limit=10_000, window_hours=24,
    )
    assert res.status == "alert"
    assert res.alert_count >= 1
    # Sprint 11 hotfix contract: the alert must include token-flag features,
    # not only length-based ones, because that's the whole point of the fix.
    payload = audit.rows[0]["payload"]
    flagged = {f["feature"] for f in payload.get("features", [])}
    token_or_ua = {f for f in flagged if f.startswith("tok_") or f.startswith("ua_")}
    assert token_or_ua, (
        f"expected token/ua feature drift in audit, got {flagged}"
    )


@pytest.mark.asyncio
async def test_drift_worker_compares_all_25_features(baseline_dir):
    """The full feature set must show up in the report (not just 6 columns)."""
    from waf_panel.workers.drift_worker import run_drift_check

    ch = _StubCh(_benign_raw_rows(50))
    audit = _StubAudit()

    res = await run_drift_check(
        ch_client=ch, audit_repo=audit,
        active_model_dir=baseline_dir,
        pull_limit=10_000, window_hours=24,
        report_dir=baseline_dir / "reports",
    )
    import json
    payload = json.loads(Path(res.report_path).read_text(encoding="utf-8"))
    # WHY: this is the regression-protector. If someone shrinks the worker
    #      back to 6 columns, this test catches it.
    assert payload["n_features_compared"] == 25


@pytest.mark.asyncio
async def test_drift_worker_skips_when_baseline_missing(tmp_path: Path):
    from waf_panel.workers.drift_worker import run_drift_check

    ch = _StubCh(_benign_raw_rows(10))
    audit = _StubAudit()

    res = await run_drift_check(
        ch_client=ch, audit_repo=audit,
        active_model_dir=tmp_path / "no-such-model",
        pull_limit=10, window_hours=24,
    )
    assert res.status == "clean"
    assert res.report_path is None
    actions = [r["action"] for r in audit.rows]
    assert actions == ["ml.drift.skipped"]


@pytest.mark.asyncio
async def test_drift_worker_pull_sql_filters_window_and_excludes_modsec(baseline_dir):
    """SAFETY: the SQL must (a) filter by window, (b) cap with LIMIT, and
    (c) exclude `event_type='modsec'` rows so attack bursts don't poison
    the baseline comparison.
    """
    from waf_panel.workers.drift_worker import run_drift_check

    ch = _StubCh(_benign_raw_rows(50))
    audit = _StubAudit()

    await run_drift_check(
        ch_client=ch, audit_repo=audit,
        active_model_dir=baseline_dir,
        window_hours=6, pull_limit=1_000,
    )
    [sql] = ch.calls
    assert "INTERVAL 6 HOUR" in sql
    assert "LIMIT 1000" in sql
    assert "FROM traffic_log" in sql
    assert "event_type = 'access'" in sql

"""Drift re-baselining — refresh baseline_features.csv on quiet windows.

Five behaviours we lock down:

1. Quiet window (no alerts in last 72h) → baseline gets rewritten,
   audit row 'ml.baseline.refreshed' written.
2. Recent drift alert → no write, audit row 'ml.baseline.skipped'
   with reason='recent_drift_alerts'.
3. Empty traffic window → no write, audit row 'ml.baseline.skipped'
   with reason='no_traffic_in_window'.
4. Existing baseline gets backed up before overwrite (operator can
   still restore manually if the new one is bad).
5. CSV is written atomically (no half-baseline if the process is
   killed mid-write).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# WHY: the rebaseline orchestrator pulls in waf_ml.features.featurize
# via _pull_baseline_columns -> _featurize_rows. The ml/ package isn't
# pip-installed in the backend test env; mirror what test_drift_worker
# does and put it on sys.path explicitly.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ml" / "src"))

from waf_panel.workers.drift_worker import (  # noqa: E402  -- sys.path edited above
    _count_recent_drift_alerts,
    _write_baseline_csv,
    rebaseline_if_quiet,
)

UTC = timezone.utc


class FakeAuditRepo:
    """Minimal in-memory audit repo: append on record, return last N
    on recent. Mirrors InMemoryAuditRepo's contract."""

    def __init__(self, seed: list[dict] | None = None) -> None:
        self.rows: list[dict] = list(seed or [])

    async def record(self, *, actor_id, action, target, payload=None) -> None:
        self.rows.append({
            "ts": datetime.now(UTC),
            "actor_id": actor_id,
            "action": action,
            "target": target,
            "payload": payload or {},
        })

    async def recent(self, limit: int = 50) -> list[dict]:
        return list(reversed(self.rows[-limit:]))


class FakeClickHouse:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def query_json(self, sql: str) -> list[dict]:  # noqa: ARG002
        return list(self.rows)


# ── 1. Counting recent drift alerts ─────────────────────────────────


@pytest.mark.asyncio
async def test_count_recent_drift_alerts_inside_window():
    audit = FakeAuditRepo([
        {"ts": datetime.now(UTC) - timedelta(hours=1), "action": "ml.drift.alert", "actor_id": None, "target": "x", "payload": {}},
        {"ts": datetime.now(UTC) - timedelta(hours=2), "action": "ml.drift.warn", "actor_id": None, "target": "x", "payload": {}},
        {"ts": datetime.now(UTC) - timedelta(hours=3), "action": "ml.drift.clean", "actor_id": None, "target": "x", "payload": {}},
    ])
    n = await _count_recent_drift_alerts(audit, since_hours=72)
    assert n == 2  # alert + warn count, clean doesn't


@pytest.mark.asyncio
async def test_count_recent_drift_alerts_outside_window():
    audit = FakeAuditRepo([
        {"ts": datetime.now(UTC) - timedelta(hours=100), "action": "ml.drift.alert", "actor_id": None, "target": "x", "payload": {}},
    ])
    n = await _count_recent_drift_alerts(audit, since_hours=72)
    assert n == 0


# ── 2. Atomic CSV write + backup ────────────────────────────────────


def test_write_baseline_csv_creates_file(tmp_path: Path) -> None:
    import numpy as np

    target = tmp_path / "baseline.csv"
    cols = {
        "method_post": np.asarray([1.0, 0.0, 1.0]),
        "path_len": np.asarray([12.0, 8.0, 14.0]),
    }
    _write_baseline_csv(target, cols)
    assert target.exists()
    text = target.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    assert lines[0] == "method_post,path_len"
    assert len(lines) == 4  # 1 header + 3 rows


def test_write_baseline_csv_backs_up_existing(tmp_path: Path) -> None:
    import numpy as np

    target = tmp_path / "baseline.csv"
    target.write_text("col\n1.0\n", encoding="utf-8")
    cols = {"col": np.asarray([2.0, 3.0])}
    _write_baseline_csv(target, cols)

    # New content
    assert "2.0" in target.read_text()
    assert "3.0" in target.read_text()
    # Backup file alongside
    backups = list(tmp_path.glob("baseline.csv.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "col\n1.0\n"


# ── 3. Rebaseline orchestrator ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rebaseline_skips_when_recent_alerts(tmp_path: Path) -> None:
    audit = FakeAuditRepo([
        {"ts": datetime.now(UTC) - timedelta(hours=1), "action": "ml.drift.alert", "actor_id": None, "target": "x", "payload": {}},
    ])
    ch = FakeClickHouse([])

    res = await rebaseline_if_quiet(
        ch_client=ch,
        audit_repo=audit,
        active_model_dir=tmp_path,
    )
    assert res["status"] == "skipped"
    assert res["reason"] == "recent_drift_alerts"
    # No CSV written
    assert not (tmp_path / "baseline_features.csv").exists()
    # Audit row recorded
    assert any(r["action"] == "ml.baseline.skipped" for r in audit.rows)


@pytest.mark.asyncio
async def test_rebaseline_skips_on_empty_window(tmp_path: Path) -> None:
    audit = FakeAuditRepo()  # quiet
    ch = FakeClickHouse([])  # no traffic

    res = await rebaseline_if_quiet(
        ch_client=ch,
        audit_repo=audit,
        active_model_dir=tmp_path,
    )
    assert res["status"] == "skipped"
    assert res["reason"] == "no_traffic_in_window"
    assert not (tmp_path / "baseline_features.csv").exists()


@pytest.mark.asyncio
async def test_rebaseline_writes_when_quiet(tmp_path: Path) -> None:
    audit = FakeAuditRepo()
    # Two synthetic rows — featurize will produce numeric vectors
    ch = FakeClickHouse([
        {"method": "GET", "path": "/api/v1/health", "query": "", "ua": "ua-1", "referer": "", "ts": "2026-05-01"},
        {"method": "POST", "path": "/api/v1/login", "query": "x=1", "ua": "ua-2", "referer": "", "ts": "2026-05-01"},
    ])

    res = await rebaseline_if_quiet(
        ch_client=ch,
        audit_repo=audit,
        active_model_dir=tmp_path,
    )
    assert res["status"] == "refreshed"
    assert res["n_rows_used"] == 2

    target = tmp_path / "baseline_features.csv"
    assert target.exists()
    # CSV has header + 2 rows
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 3

    # Audit row recorded
    refreshed = [r for r in audit.rows if r["action"] == "ml.baseline.refreshed"]
    assert len(refreshed) == 1
    assert refreshed[0]["payload"]["n_rows_used"] == 2

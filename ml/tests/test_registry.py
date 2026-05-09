"""registry.py SQL plumbing — verified without a real Postgres.

WHY: psycopg-against-real-pg is integration territory and a pain in CI.
     Here we stub `psycopg.connect`, capture every (sql, params) pair the
     function fires, and assert the contract: upsert SQL, deactivate-all
     when activate=True, the activate-this-id update afterwards, single
     transaction (commit at the end).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from uuid import UUID

import pytest

# ── Fake psycopg module ─────────────────────────────────────────────────
# WHY: registry.py does `import psycopg` lazily inside register/get_active.
#      We install a fake `psycopg` into sys.modules before importing the
#      registry, so the real driver never has to be available in CI.

class _FakeCursor:
    def __init__(self, log: list[tuple[str, tuple]]):
        self._log = log
        self._next_row: tuple | None = None

    # Context manager so `with conn.cursor() as cur:` works.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple = ()) -> None:  # type: ignore[override]
        self._log.append((sql, params))
        # WHY: only the upsert RETURNING needs to surface a row to the caller.
        if "RETURNING" in sql:
            self._next_row = (
                UUID("11111111-2222-3333-4444-555555555555"),
                "synthetic-v1-2026-05-08T10:00:00+00:00-xgboost",
                "xgboost",
                "ml/models/v_test/xgboost.pkl",
                {"f1": 0.95},
                False,  # is_active is then flipped by the second update
            )

    def fetchone(self):
        return self._next_row

    def fetchall(self):
        return [self._next_row] if self._next_row else []


class _FakeConnection:
    def __init__(self, log: list[tuple[str, tuple]]):
        self._log = log
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._log)

    def commit(self) -> None:
        self.commit_calls += 1


@pytest.fixture
def fake_psycopg(monkeypatch):
    log: list[tuple[str, tuple]] = []
    fake = types.ModuleType("psycopg")

    def fake_connect(_dsn, autocommit=False):  # noqa: ARG001
        return _FakeConnection(log)

    fake.connect = fake_connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    # Drop any cached registry module from previous tests so the
    # `import psycopg` inside register() re-binds to our fake.
    monkeypatch.delitem(sys.modules, "waf_ml.registry", raising=False)
    return log


def test_register_upserts_and_does_not_touch_other_rows(fake_psycopg):
    log = fake_psycopg
    from waf_ml.registry import register

    res = register(
        version="csic-2010-2026-05-08T10:00:00+00:00-xgboost",
        algo="xgboost",
        trained_at="2026-05-08T10:00:00+00:00",
        dataset="csic-2010",
        metrics={"f1": 0.95, "recall": 0.93},
        artifact_path=Path("/tmp/xgboost.pkl"),
        activate=False,
        dsn="postgresql://stub",
    )
    sqls = [s for s, _ in log]
    # SAFETY: with activate=False, the global "deactivate all" UPDATE must NOT fire.
    assert not any("UPDATE ml_models SET is_active = FALSE" in s for s in sqls)
    # Exactly one SQL should be the upsert.
    upserts = [s for s in sqls if "INSERT INTO ml_models" in s]
    assert len(upserts) == 1
    # And no follow-up `is_active = TRUE` flip.
    assert not any("is_active = TRUE" in s for s in sqls)

    assert res.is_active is False
    assert res.algo == "xgboost"


def test_register_with_activate_runs_full_flip_sequence(fake_psycopg):
    log = fake_psycopg
    from waf_ml.registry import register

    res = register(
        version="csic-2010-2026-05-08T10:00:00+00:00-xgboost",
        algo="xgboost",
        trained_at="2026-05-08T10:00:00+00:00",
        dataset="csic-2010",
        metrics={"f1": 0.95},
        artifact_path=Path("/tmp/xgboost.pkl"),
        activate=True,
        dsn="postgresql://stub",
    )
    sqls = [s for s, _ in log]

    # Order matters: deactivate everything FIRST, then upsert, then flip the new one.
    deact = next(i for i, s in enumerate(sqls) if "is_active = FALSE" in s)
    upsert = next(i for i, s in enumerate(sqls) if "INSERT INTO ml_models" in s)
    activate_one = next(i for i, s in enumerate(sqls) if "is_active = TRUE" in s)
    assert deact < upsert < activate_one

    assert res.is_active is True


def test_register_artifact_path_normalised_to_posix(fake_psycopg):
    log = fake_psycopg
    from waf_ml.registry import register

    register(
        version="x", algo="lr",
        trained_at="2026-05-08T10:00:00+00:00",
        dataset="synthetic-v1",
        metrics={},
        artifact_path=Path("ml") / "models" / "v_test" / "lr.pkl",
        activate=False,
        dsn="postgresql://stub",
    )
    upsert_params = next(p for s, p in log if "INSERT INTO ml_models" in s)
    # SAFETY: stored as POSIX so a Linux backend can re-open a path
    #         a Windows trainer wrote.
    artifact_value = upsert_params[5]
    assert "\\" not in artifact_value
    assert artifact_value.endswith("ml/models/v_test/lr.pkl")


def test_register_metrics_serialised_as_json(fake_psycopg):
    log = fake_psycopg
    from waf_ml.registry import register

    register(
        version="x", algo="lr",
        trained_at="2026-05-08T10:00:00+00:00",
        dataset="synthetic-v1",
        metrics={"f1": 0.91, "recall": 0.88, "fpr_at_recall_0_99": 0.012},
        artifact_path=Path("/tmp/lr.pkl"),
        activate=False,
        dsn="postgresql://stub",
    )
    upsert_params = next(p for s, p in log if "INSERT INTO ml_models" in s)
    metrics_blob = upsert_params[4]
    assert isinstance(metrics_blob, str)  # jsonb takes a JSON-text param
    import json
    decoded = json.loads(metrics_blob)
    assert decoded["f1"] == pytest.approx(0.91)


def test_get_active_returns_none_when_no_row(monkeypatch):
    """Empty-table case must give back None, not raise."""
    log: list[tuple[str, tuple]] = []
    fake = types.ModuleType("psycopg")

    class EmptyCursor(_FakeCursor):
        def execute(self, sql, params=()):
            log.append((sql, params))
            self._next_row = None  # registry expects None for "no active row"

    class EmptyConn(_FakeConnection):
        def cursor(self):
            return EmptyCursor(log)

    fake.connect = lambda _dsn, autocommit=False: EmptyConn(log)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.delitem(sys.modules, "waf_ml.registry", raising=False)

    from waf_ml.registry import get_active
    assert get_active(dsn="postgresql://stub") is None

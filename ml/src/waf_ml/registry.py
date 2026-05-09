"""Model registry — pickle on disk, metadata row in PostgreSQL.

WHY: the trainer must stay standalone. We talk to Postgres directly via
     psycopg, NOT through the FastAPI ORM, so a `pip install waf-ml` env
     never has to import SQLAlchemy or anything from the gateway image.

Schema (see infra/postgres/init.sql):

    ml_models(id, version, algo, trained_at, dataset, metrics jsonb,
              artifact_path, is_active)

SAFETY: only one row may be `is_active = TRUE` (partial unique index).
        `register(..., activate=True)` flips others off in the same tx.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

# WHY: psycopg3 is imported lazily so `import waf_ml.registry` works in
#      tests that never touch Postgres (e.g. golden-feature comparison).


@dataclass
class RegisteredModel:
    id: UUID
    version: str
    algo: str
    artifact_path: Path
    metrics: dict[str, Any]
    is_active: bool


def _dsn() -> str:
    """Build a libpq DSN from the same env vars the backend uses.

    NOTE: trainer runs from a developer host (or a CI runner), not inside
          the FastAPI image, so we read POSTGRES_* directly instead of
          importing waf_panel.config.
    """
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "waf")
    pwd = os.environ.get("POSTGRES_PASSWORD", "waf_dev_only")
    db = os.environ.get("POSTGRES_DB", "waf")
    return f"host={host} port={port} user={user} password={pwd} dbname={db}"


def _normalise_artifact_path(p: Path) -> str:
    """Store as POSIX so it's portable between Windows trainers and Linux readers."""
    return p.as_posix()


def register(
    *,
    version: str,
    algo: str,
    trained_at: str,           # ISO-8601 string from EvalReport
    dataset: str,
    metrics: dict[str, Any],
    artifact_path: Path,
    activate: bool = False,
    dsn: str | None = None,
) -> RegisteredModel:
    """Insert (or upsert) a model row. Optionally mark it active.

    SAFETY: when activate=True, all *other* rows are deactivated in the
            same transaction so the partial unique index never trips.
    """
    import psycopg  # local import — see module docstring

    sql_upsert = """
        INSERT INTO ml_models
              (version, algo, trained_at, dataset, metrics, artifact_path, is_active)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (version) DO UPDATE
           SET algo          = EXCLUDED.algo,
               trained_at    = EXCLUDED.trained_at,
               dataset       = EXCLUDED.dataset,
               metrics       = EXCLUDED.metrics,
               artifact_path = EXCLUDED.artifact_path
         RETURNING id, version, algo, artifact_path, metrics, is_active;
    """

    with psycopg.connect(dsn or _dsn(), autocommit=False) as conn:
        with conn.cursor() as cur:
            if activate:
                cur.execute("UPDATE ml_models SET is_active = FALSE WHERE is_active;")
            cur.execute(
                sql_upsert,
                (
                    version,
                    algo,
                    trained_at,
                    dataset,
                    json.dumps(metrics),
                    _normalise_artifact_path(artifact_path),
                    activate,
                ),
            )
            row = cur.fetchone()
            if activate:
                cur.execute(
                    "UPDATE ml_models SET is_active = TRUE WHERE id = %s;",
                    (row[0],),
                )
        conn.commit()

    return RegisteredModel(
        id=row[0],
        version=row[1],
        algo=row[2],
        artifact_path=Path(row[3]),
        metrics=row[4] if isinstance(row[4], dict) else json.loads(row[4]),
        is_active=bool(activate),
    )


def get_active(*, algo: str | None = None, dsn: str | None = None) -> RegisteredModel | None:
    """Return the currently active model row, or None.

    NOTE: `algo` filter is provided for Sprint 8's online inference path,
          which may want the active *xgboost* specifically.
    """
    import psycopg

    sql = (
        "SELECT id, version, algo, artifact_path, metrics, is_active "
        "FROM ml_models WHERE is_active = TRUE"
    )
    params: tuple[Any, ...] = ()
    if algo is not None:
        sql += " AND algo = %s"
        params = (algo,)
    sql += " LIMIT 1;"

    with psycopg.connect(dsn or _dsn()) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return RegisteredModel(
            id=row[0],
            version=row[1],
            algo=row[2],
            artifact_path=Path(row[3]),
            metrics=row[4] if isinstance(row[4], dict) else json.loads(row[4]),
            is_active=True,
        )


def list_all(*, dsn: str | None = None) -> list[RegisteredModel]:
    """All registered rows, newest trained_at first. Useful for `waf-ml ls`."""
    import psycopg

    with psycopg.connect(dsn or _dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, version, algo, artifact_path, metrics, is_active "
            "FROM ml_models ORDER BY trained_at DESC;"
        )
        rows = cur.fetchall()

    return [
        RegisteredModel(
            id=r[0],
            version=r[1],
            algo=r[2],
            artifact_path=Path(r[3]),
            metrics=r[4] if isinstance(r[4], dict) else json.loads(r[4]),
            is_active=bool(r[5]),
        )
        for r in rows
    ]


__all__ = ["RegisteredModel", "register", "get_active", "list_all"]

"""Alembic guardrails — offline SQL render must mention every model table."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_offline_upgrade_emits_sql() -> None:
    # WHY: this is the single check we can run without a real database.
    #      It catches missing `op.create_table` calls, broken metadata refs,
    #      and the trio of "I forgot to import the model" mistakes.
    res = subprocess.run(
        ["alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": __import__("os").environ.get("PATH", ""),
            "PYTHONPATH": str(BACKEND / "src"),
            "JWT_SECRET": "test-secret-test-secret-test",
            "POSTGRES_HOST": "localhost",
        },
    )
    assert res.returncode == 0, res.stderr
    sql = res.stdout
    for table in ("users", "rules", "ml_models", "incidents", "audit_log"):
        assert f"CREATE TABLE {table}" in sql, f"missing CREATE TABLE for {table}"
    # WHY: extensions are required by the schema; loss of either breaks the boot.
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql
    assert "CREATE EXTENSION IF NOT EXISTS citext" in sql

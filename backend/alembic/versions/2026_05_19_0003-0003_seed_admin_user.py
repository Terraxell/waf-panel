"""Seed default admin user — Sprint 14 hotfix.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19

WHY: smoke-testing v1.1.0 against a clean docker-compose stack revealed
a real production gap — neither ``infra/postgres/init.sql`` nor any
prior migration seeds an admin user. The login screen's hint string
("Default admin: admin@example.com / admin") promises something that
isn't actually there. This migration closes that gap by inserting the
default admin row idempotently.

Three deliberate choices, called out so a future operator doesn't fight
the migration:

1. **Hardcoded argon2id hash for password "admin".**
   Computing argon2id at migration time would require a dependency
   (passlib + argon2-cffi) inside Alembic's env, and it would change the
   hash on every run because of the random salt — making the migration
   non-idempotent against itself. Hardcoding is the same trade-off the
   ``waf_panel.tests.conftest`` makes (same hash literal, even).

2. **`ON CONFLICT (email) DO NOTHING`, never DO UPDATE.**
   The migration must NEVER overwrite a password that an operator has
   rotated. So if the row already exists with whatever hash, we leave
   it alone. The migration is one-shot for the bootstrap case.

3. **Default password is `admin`, matching the documented hint.**
   This is acceptable for a dev/course-project default. Production
   deployments must change it on first login (or override via
   `BOOTSTRAP_ADMIN_PASSWORD` once we add CLI support — out of scope
   for this hotfix; tracked as Sprint 14 follow-up).

The hash below is the same one used in ``backend/tests/conftest.py``
(``ADMIN_PASSWORD_HASH``) so test fixtures and a fresh deploy share
a single source of truth for "default admin / password".
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# WHY this exact value: argon2id hash of the literal string "admin",
# generated once with `python -m passlib.hash.argon2 -s admin`. Mirrors
# the hash in tests/conftest.py — keep them in sync.
_ADMIN_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$kfIew9gbYywFQIjxXgtBiA$"
    "WiPS5bz9F8qvwWc2Woi51gNJvGCLUltunbZCcWUbl7o"
)
# WHY a deterministic UUID: tests reference it (`ADMIN_ID`), and the
# audit_log foreign key constraint hands us the same id across reboots.
_ADMIN_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # WHY no `op.bulk_insert` here: it would emit a multi-row INSERT
    # without a per-row ON CONFLICT clause. Plain SQL is clearer for a
    # single-row idempotent seed and survives offline-mode --sql output.
    op.execute(
        f"""
        INSERT INTO users (id, email, password_hash, role, is_active)
        VALUES (
            '{_ADMIN_ID}',
            'admin@example.com',
            '{_ADMIN_HASH}',
            'admin',
            true
        )
        ON CONFLICT (email) DO NOTHING
        """
    )


def downgrade() -> None:
    # WHY only delete the seeded id, not by email: an operator may have
    # legitimately renamed the admin account; downgrade should remove
    # only what this migration created. If the id was reassigned, the
    # operator is responsible for the manual cleanup.
    op.execute(f"DELETE FROM users WHERE id = '{_ADMIN_ID}'")

"""waf-panel CLI — admin password rotation, future bootstrap helpers.

Usage:
    python -m waf_panel.cli rotate-admin --email admin@example.com --password 'new-pwd'
    python -m waf_panel.cli rotate-admin --email admin@example.com   # prompt for password

WHY a CLI: the production guard refuses to start when the seeded admin
still has the default password 'admin' (see main.py::_check_admin_password).
The runbook documents a psql snippet, but a CLI that uses the same
hash_password() the rest of the app uses is fewer steps and harder to
get wrong (no shell quoting on the argon2 hash, no risk of pasting a
trailing newline into the column).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import update

from .config import get_settings
from .db.models import User
from .db.session import get_sessionmaker
from .security import hash_password


async def _rotate_admin(email: str, password: str) -> int:
    """Update the password_hash of the user identified by `email`.

    Returns 0 on success, 2 if the user was not found, 3 on any other
    DB error. Mirrors the unix convention: 0 success, 1 generic error,
    >=2 specific failures the operator can grep on.
    """
    if len(password) < 8:
        print("error: password must be at least 8 characters", file=sys.stderr)
        return 1

    settings = get_settings()
    print(f"[cli] connecting to {settings.postgres_host}:{settings.postgres_port}")

    sm = get_sessionmaker()
    new_hash = hash_password(password)
    async with sm() as session:
        try:
            stmt = (
                update(User)
                .where(User.email == email)
                .values(password_hash=new_hash)
                .returning(User.id, User.email)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                print(f"error: no user with email {email!r}", file=sys.stderr)
                return 2
            await session.commit()
            print(f"[cli] rotated password for {row.email} (id={row.id})")
            print(
                "[cli] WAF_ENV=production guard will now allow boot if the "
                "JWT_SECRET is also set."
            )
            return 0
        except Exception as e:  # noqa: BLE001 -- CLI tool, surface the message
            print(f"error: db failure: {e}", file=sys.stderr)
            return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waf_panel.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rot = sub.add_parser(
        "rotate-admin",
        help="Rotate an admin (or any user) password to bypass the boot guard.",
    )
    rot.add_argument(
        "--email",
        default="admin@example.com",
        help="Account to rotate. Defaults to the seeded admin.",
    )
    rot.add_argument(
        "--password",
        default=None,
        help=(
            "New password. If omitted, the CLI prompts (no echo) so the "
            "value never lands in shell history."
        ),
    )

    args = parser.parse_args(argv)
    if args.cmd != "rotate-admin":
        parser.error(f"unknown subcommand: {args.cmd}")

    pwd = args.password
    if pwd is None:
        pwd = getpass.getpass(f"new password for {args.email}: ")
        confirm = getpass.getpass("confirm: ")
        if pwd != confirm:
            print("error: passwords do not match", file=sys.stderr)
            return 1

    return asyncio.run(_rotate_admin(args.email, pwd))


if __name__ == "__main__":
    sys.exit(main())

"""Admin password rotation CLI — tests.

WHY: the CLI is the operator-facing way out of the production startup
guard (main.py::_check_admin_password). It calls the same hash_password
the auth path uses, so verify_password against the rotated string must
succeed afterwards.

These tests exercise the *pure* helper. The async _rotate_admin is
covered indirectly via the argparse path, but not against a live PG --
that's an integration concern.
"""

from __future__ import annotations

import pytest


def test_main_rejects_short_password(capsys):
    from waf_panel.cli import main

    rc = main(["rotate-admin", "--email", "x@y.com", "--password", "1234567"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "at least 8 characters" in err


def test_main_requires_subcommand():
    from waf_panel.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code != 0  # argparse exits non-zero on missing subcmd


def test_main_unknown_subcommand_errors():
    from waf_panel.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["totally-not-a-subcommand"])
    assert exc_info.value.code != 0


def test_main_prompts_when_password_omitted(monkeypatch, capsys):
    """No --password flag → getpass twice → mismatching values → exit 1
    with a clear message, no DB call attempted."""
    from waf_panel import cli

    inputs = iter(["one-password-aB", "different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(inputs))

    rc = cli.main(["rotate-admin", "--email", "x@y.com"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "do not match" in err


def test_main_calls_rotate_when_passwords_match(monkeypatch):
    """When prompts match, _rotate_admin is invoked with the typed
    value. We mock the async helper so the test stays unit-scope."""
    from waf_panel import cli

    captured: dict[str, str] = {}

    async def fake_rotate(email: str, password: str) -> int:
        captured["email"] = email
        captured["password"] = password
        return 0

    monkeypatch.setattr(cli, "_rotate_admin", fake_rotate)
    pw = "matching-password-123"
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": pw)

    rc = cli.main(["rotate-admin", "--email", "ops@example.com"])
    assert rc == 0
    assert captured == {"email": "ops@example.com", "password": pw}


def test_rotate_admin_validates_password_length():
    """The async helper itself also checks length (defence in depth --
    in case the CLI path is bypassed and someone calls _rotate_admin
    from a Python REPL)."""
    import asyncio

    from waf_panel.cli import _rotate_admin

    # Length check is the FIRST gate; we don't even get to the DB.
    rc = asyncio.run(_rotate_admin("x@y.com", "short"))
    assert rc == 1

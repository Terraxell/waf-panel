"""Test fixtures — in-memory repos and ClickHouse mock for every test."""

import os
from collections.abc import Iterator
from uuid import UUID

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

import pytest
from fastapi.testclient import TestClient

from waf_panel.clickhouse_client import (
    InMemoryClickHouseClient,
    reset_in_memory_clickhouse,
    use_in_memory_clickhouse,
)
from waf_panel.repositories.deps import reset_in_memory, use_in_memory
from waf_panel.repositories.memory import _UserRow

ADMIN_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$kfIew9gbYywFQIjxXgtBiA$WiPS5bz9F8qvwWc2Woi51gNJvGCLUltunbZCcWUbl7o"
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def in_memory_repos() -> Iterator[InMemoryClickHouseClient]:
    """Switch repositories AND ClickHouse to in-memory for every test.

    Also clears the login rate-limit bucket between cases so that
    repeated admin_token fixture calls don't fill the (testclient-ip,
    admin@example.com) bucket and trip a 429 on the 6th test.
    """
    from waf_panel.security_rate_limit import reset_for_tests as reset_rl

    reset_rl()
    use_in_memory(seed_users=[
        _UserRow(
            id=ADMIN_ID,
            email="admin@example.com",
            password_hash=ADMIN_PASSWORD_HASH,
            role="admin",
            is_active=True,
        ),
    ])
    ch = use_in_memory_clickhouse()
    yield ch
    reset_in_memory()
    reset_in_memory_clickhouse()
    reset_rl()


@pytest.fixture
def client() -> TestClient:
    from waf_panel.main import create_app
    return TestClient(create_app())


@pytest.fixture
def admin_token(client: TestClient) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200, res.text
    # ADR-0014: login also plants session + CSRF cookies on the shared
    # TestClient. Tests that use this fixture want a Bearer token only;
    # the lingering cookies would change the CSRF middleware path on
    # subsequent requests ("no auth header" tests would see 403 instead
    # of 401). Strip the cookies so the fixture is side-effect-free.
    client.cookies.clear()
    return res.json()["access_token"]

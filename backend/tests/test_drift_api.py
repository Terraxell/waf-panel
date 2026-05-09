"""Drift-report API — Sprint 13 (audit C-list item 18c)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _auth(_client, admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def reports_dir(tmp_path: Path, monkeypatch):
    """Point the API at a tmp dir + seed two reports (one alert, one clean)."""
    d = tmp_path / "drift_reports"
    d.mkdir()
    (d / "drift-20260601T120000Z.json").write_text(
        json.dumps({
            "generated_at": "2026-06-01T12:00:00",
            "status": "alert",
            "alert_count": 3,
            "warn_count": 1,
            "n_rows_checked": 12345,
            "n_features_compared": 25,
            "features": [
                {"feature": "tok_union_select", "psi": 0.42, "ks_pvalue": 0.001, "level": "alert"},
                {"feature": "len_query", "psi": 0.05, "ks_pvalue": 0.6, "level": "clean"},
            ],
        }),
        encoding="utf-8",
    )
    (d / "drift-20260601T080000Z.json").write_text(
        json.dumps({
            "generated_at": "2026-06-01T08:00:00",
            "status": "clean",
            "alert_count": 0,
            "warn_count": 0,
            "n_rows_checked": 9000,
            "n_features_compared": 25,
            "features": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("DRIFT_REPORTS_DIR", str(d))
    return d


def test_list_reports_newest_first(client, admin_token, reports_dir):
    r = client.get("/api/v1/drift", headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    # newer (12:00:00 file) before older (08:00:00 file)
    assert body[0]["name"] > body[1]["name"]
    assert body[0]["status"] == "alert"
    assert body[1]["status"] == "clean"


def test_list_reports_returns_empty_when_dir_missing(client, admin_token, monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFT_REPORTS_DIR", str(tmp_path / "no-such"))
    r = client.get("/api/v1/drift", headers=_auth(client, admin_token))
    assert r.status_code == 200
    assert r.json() == []


def test_list_requires_auth(client, reports_dir):
    r = client.get("/api/v1/drift")
    assert r.status_code == 401


def test_get_specific_report(client, admin_token, reports_dir):
    r = client.get(
        "/api/v1/drift/drift-20260601T120000Z.json",
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alert"
    assert body["alert_count"] == 3
    assert body["n_features_compared"] == 25
    assert len(body["features"]) == 2


def test_get_unknown_report_404(client, admin_token, reports_dir):
    r = client.get(
        "/api/v1/drift/drift-19990101T000000Z.json",
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 404


def test_traversal_attempts_rejected(client, admin_token, reports_dir):
    """SAFETY: ../ and / and \\ in names are 400 — never reach the filesystem."""
    for bad in [
        "../etc/passwd",
        "drift-../../etc/passwd",
        "drift-bad\\..\\..\\etc.json",
        "drift-..\\..\\windows.json",
        "/etc/passwd",
    ]:
        r = client.get(
            f"/api/v1/drift/{bad}",
            headers=_auth(client, admin_token),
        )
        assert r.status_code in (400, 404), f"{bad} got {r.status_code}"


def test_filename_pattern_enforced(client, admin_token, reports_dir):
    """Only `drift-*.json` is accepted — anything else is 400 even if it
    happens to live in the reports dir."""
    # Create a file that doesn't match the pattern.
    (reports_dir / "secret.txt").write_text("nope", encoding="utf-8")
    r = client.get(
        "/api/v1/drift/secret.txt",
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 400


def test_corrupt_report_falls_through_in_list(client, admin_token, reports_dir):
    """A garbage file in the dir doesn't break the listing — it's skipped."""
    (reports_dir / "drift-bad.json").write_text("{not json", encoding="utf-8")
    r = client.get("/api/v1/drift", headers=_auth(client, admin_token))
    assert r.status_code == 200
    names = {x["name"] for x in r.json()}
    # The corrupt file is skipped; the good ones still listed.
    assert "drift-bad.json" not in names
    assert len(r.json()) == 2

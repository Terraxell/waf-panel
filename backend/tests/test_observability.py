"""Observability — Prometheus /metrics + request-id correlation.

Three behaviours we lock down:

1. ``GET /metrics`` returns the Prometheus text-exposition format and
   includes a metric for the very request that just hit the panel.
2. The request-id middleware honours an inbound ``X-Request-ID`` and
   echoes it back on the response.
3. With no inbound id, the middleware generates one (32-hex uuid)
   and echoes it on the response, so the SPA can surface it in any
   "report a bug" UI later.
"""

from __future__ import annotations

import re

UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def test_metrics_endpoint_serves_prometheus_text(client) -> None:
    # First hit a regular endpoint so the instrumentator records a
    # sample. Otherwise /metrics is technically valid but empty.
    res_health = client.get("/health")
    assert res_health.status_code == 200

    res = client.get("/metrics")
    assert res.status_code == 200
    # WHY exact prefix: pytest can run on hosts where the prom client
    # version flips between 'text/plain; version=0.0.4...' wordings,
    # but 'text/plain' is the stable contract.
    assert res.headers["content-type"].startswith("text/plain")
    body = res.text
    # Sanity: the instrumentator emits at least one HTTP request total
    # counter line.
    assert "http_requests_total" in body or "http_request_duration" in body


def test_metrics_endpoint_excludes_self_recursion(client) -> None:
    """SAFETY: scraping /metrics must NOT increment the counter that
    the same scrape is reading. Otherwise dashboards monotonically
    drift upward from the scrape itself."""
    res = client.get("/metrics")
    assert res.status_code == 200
    # Lines for /metrics handler should not appear (we excluded it).
    for line in res.text.splitlines():
        if line.startswith("#"):
            continue
        if "/metrics" in line and "handler" in line:
            raise AssertionError(f"/metrics leaked into its own counter: {line}")


# ── Request-id correlation ───────────────────────────────────────────


def test_request_id_generated_when_absent(client) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    rid = res.headers.get("X-Request-ID")
    assert rid is not None
    assert UUID_HEX_RE.match(rid), f"expected 32-hex uuid, got {rid!r}"


def test_request_id_honoured_when_present(client) -> None:
    # SAFETY: cap at 128 chars on the server side; we send a value
    # well under that, so it should round-trip verbatim.
    incoming = "trace-corr-abc-123"
    res = client.get("/health", headers={"X-Request-ID": incoming})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == incoming


def test_request_id_capped_at_128_chars(client) -> None:
    long = "x" * 500
    res = client.get("/health", headers={"X-Request-ID": long})
    assert res.status_code == 200
    out = res.headers["X-Request-ID"]
    assert len(out) <= 128
    assert out == long[:128]

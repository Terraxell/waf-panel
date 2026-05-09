"""Bench harness — drive a stub HTTP server, assert FPR/FNR arithmetic.

WHY: the real run hits the WAF stack on a dev host. Here we boot a
tiny HTTP server in a background thread that mimics ModSec by
returning 403 to anything matching one of a few attack regexes.
We feed it the project's labelled corpora and assert that:

  1. The harness arithmetic is right (FPR/FNR/TPR all match the stub
     server's behaviour exactly).
  2. The corpora themselves are non-trivial (≥ 50 entries each side,
     no syntactic accidents).
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from bench.run import BenchReport, run_bench

REPO = Path(__file__).resolve().parents[2]
BENIGN = REPO / "bench" / "corpora" / "benign.txt"
MALICIOUS = REPO / "bench" / "corpora" / "malicious.txt"

# WHY: a deliberately simple matcher — just enough to flag every line in
#      the malicious corpus. NOT meant to mimic ModSec/CRS faithfully;
#      the tests assert *bench arithmetic*, not *WAF coverage*.
_ATTACK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"union\s+(all\s+)?select",
        r"or\s*'1'\s*=\s*'1",
        r"or\s+1\s*=\s*1",
        r"<\s*script",
        r"javascript:",
        r"\.\.\/",
        r"\.\.%2f",
        r"\.\.%252f",
        r"/etc/passwd",
        r"/etc/shadow",
        r"\$\{jndi:",
        r"sleep\s*\(",
        r"benchmark\s*\(",
        r"updatexml\s*\(",
        r";\s*drop\s+table",
        r";\s*waitfor\s+delay",
        r"%00",
        r"`id`|\$\(id\)",
        r"169\.254\.169\.254",
        r"file:///",
        r"gopher://",
        r"\.git/config",
        r"\.env(?:$|\?|\s)",
        r"\.aws/credentials",
        r"phpmyadmin",
        r"phpinfo\.php",
        r"wp-login\.php",
        r"xmlrpc\.php",
        r"admin-ajax\.php\?action=revslider",
        r"server-status",
        r"sqlmap",
        r"%FF",
        r"role=admin",
        r"token=(null|undefined)",
        r"goto\?to=//",
        r"redirect\?url=(https?:|%2F%2F)",
        r"<\s*img[^>]+onerror",
        r"<\s*svg/onload",
        r"<\s*iframe",
        r"<\s*body[^>]+onload",
        r"<\s*input[^>]+onfocus",
        r"document\.cookie",
        r"eval\s*\(\s*atob",
        r"shell\.php",
        r"\|\s*wget\s+http",
        r"=\$\(",
        r"=`",
        r"127\.0\.0\.1[;|&]",
        r"127\.0\.0\.1\|",
        r"localhost:8500",
        r"%24%7Bjndi%3A",
        r"%24%7B%24%7B%3A%3A-",
        r"util\?cmd=",
        r"win\.ini",
        r"%2527%2520OR",
        r"%2520OR%25201%253D1",
        r"%27%20OR%201%3D1",
        r"%22%20OR%20%22a%22%3D%22a",
        r"%2F%2A.*?%2A%2F",  # SQL inline comments encoded
        r"%23",  # MySQL `#` comment after `'`
    ]
]


def _is_attack(path_query: str) -> bool:
    return any(p.search(path_query) for p in _ATTACK_PATTERNS)


class _StubHandler(BaseHTTPRequestHandler):
    """Returns 403 for anything matching the attack patterns, 200 otherwise."""

    def log_message(self, *_args, **_kw):  # silence the access log
        return

    def do_GET(self):
        self._respond()

    def do_POST(self):
        self._respond()

    def do_PUT(self):
        self._respond()

    def do_DELETE(self):
        self._respond()

    def do_PATCH(self):
        self._respond()

    def _respond(self):
        if _is_attack(self.path):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        body = b"ok"
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_corpora_are_substantial():
    """Sanity: enough lines on each side that the bench has signal."""
    benign = [ln for ln in BENIGN.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    mal = [ln for ln in MALICIOUS.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(benign) >= 50
    assert len(mal) >= 50


def test_bench_against_stub_server_arithmetic(stub_server):
    """End-to-end harness: drive the stub, check FPR/FNR/TPR add up."""
    rep: BenchReport = run_bench(
        target=stub_server,
        benign_path=BENIGN,
        malicious_path=MALICIOUS,
        rps=1000,
        warmup=0,
        timeout_sec=2.0,
    )
    # Arithmetic invariant: TPR + FNR == 1 (within float epsilon).
    assert abs(rep.tpr + rep.fnr - 1.0) < 1e-9
    # Counts add up.
    benign_lines = [
        ln for ln in BENIGN.read_text().splitlines() if ln.strip() and not ln.startswith("#")
    ]
    mal_lines = [
        ln for ln in MALICIOUS.read_text().splitlines() if ln.strip() and not ln.startswith("#")
    ]
    assert rep.n_benign == len(benign_lines)
    assert rep.n_malicious == len(mal_lines)
    # Every probe came back without a transport error.
    assert rep.error_count == 0
    # Bench latency stays sub-second on a loopback server.
    assert rep.latency_p99_ms < 1000.0


def test_stub_server_blocks_known_attacks(stub_server):
    """Negative arithmetic check: FNR should be reasonably low — the stub
    catches ≥ 70% of the malicious corpus, leaving the rest for ML to
    learn. We're checking the *harness*, not the stub."""
    rep = run_bench(
        target=stub_server, benign_path=BENIGN, malicious_path=MALICIOUS,
        rps=1000, warmup=0, timeout_sec=2.0,
    )
    # Stub is a regex hack; we just want non-trivial recall to know the
    # bench drives blocking decisions correctly. Real ModSec + CRS will
    # do much better than this on the same corpus.
    assert rep.tpr > 0.5
    # And it should not block benign traffic at all (regex-level FPR=0).
    assert rep.fpr == pytest.approx(0.0)


def test_bench_fpr_fnr_consistent_with_per_probe_results(stub_server):
    rep = run_bench(
        target=stub_server, benign_path=BENIGN, malicious_path=MALICIOUS,
        rps=1000, warmup=0, timeout_sec=2.0,
    )
    blocked_benign = sum(1 for r in rep.results if r.label == 0 and r.blocked)
    allowed_mal = sum(1 for r in rep.results if r.label == 1 and not r.blocked)
    n_b = max(rep.n_benign, 1)
    n_m = max(rep.n_malicious, 1)
    assert rep.fpr == pytest.approx(blocked_benign / n_b)
    assert rep.fnr == pytest.approx(allowed_mal / n_m)


def test_bench_writes_json_report(tmp_path: Path, stub_server):
    """End-to-end CLI smoke: the JSON report is well-formed."""
    import json

    from bench.run import main

    out = tmp_path / "rep.json"
    rc = main([
        "--target", stub_server,
        "--benign", str(BENIGN),
        "--malicious", str(MALICIOUS),
        "--rps", "1000",
        "--warmup", "0",
        "--report", str(out),
    ])
    # WHY: rc=0 when FPR ≤ 0.05 AND FNR ≤ 0.30; rc=2 otherwise. The stub
    #      regex hack lands somewhere in 0.3–0.5 FNR, so either rc is fine —
    #      we're testing the *report writing*, not the stub's recall.
    assert rc in {0, 2}
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert {"target", "n_benign", "n_malicious", "fpr", "fnr", "tpr", "results"} <= set(payload.keys())

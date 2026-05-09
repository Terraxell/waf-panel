"""Attack-bench harness — drives a labelled corpus against a target URL,
collects FPR/FNR/p50/p95/p99 latency, and writes a JSON report.

WHY: CP-3 of the methodology asks for measured numbers, not "we tested
it manually". The harness is dependency-light (stdlib + httpx) so it
runs on the same host that runs the stack — `make bench` after
`make up`. The protective decision is taken from the response status:
HTTP 403 ⇒ blocked, anything else ⇒ allowed.

Usage:
    python -m bench.run \
        --target http://localhost:8080 \
        --benign  bench/corpora/benign.txt \
        --malicious bench/corpora/malicious.txt \
        --report  bench/reports/$(date +%Y%m%dT%H%M%S).json \
        --rps     20 \
        --warmup  5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


@dataclass
class Probe:
    method: str
    path_query: str
    label: int  # 0 benign, 1 malicious


@dataclass
class ProbeResult:
    method: str
    path_query: str
    label: int
    status: int
    blocked: bool
    latency_ms: float
    error: str | None = None


@dataclass
class BenchReport:
    target: str
    n_benign: int
    n_malicious: int
    fpr: float            # benign-blocked / benign  (smaller is better)
    fnr: float            # malicious-allowed / malicious  (smaller is better)
    tpr: float            # 1 - fnr
    accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_count: int
    duration_sec: float
    results: list[ProbeResult]


def _parse_corpus(path: Path, label: int) -> list[Probe]:
    """One METHOD PATH?QUERY per line; `#` and blank lines skipped."""
    out: list[Probe] = []
    if not path.exists():
        raise SystemExit(f"corpus not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split(maxsplit=1)
        if len(parts) == 1:
            method, path_query = "GET", parts[0]
        else:
            method, path_query = parts[0], parts[1]
        out.append(Probe(method=method.upper(), path_query=path_query, label=label))
    return out


async def _fire(
    client: httpx.AsyncClient,
    probe: Probe,
    target: str,
) -> ProbeResult:
    started = time.perf_counter()
    try:
        # WHY: don't follow redirects — a 302 to /login isn't a "block",
        #      and we don't want chasing redirects to pollute latency.
        url = target.rstrip("/") + probe.path_query
        if probe.method == "GET":
            res = await client.get(url, follow_redirects=False)
        else:
            res = await client.request(probe.method, url, follow_redirects=False)
    except httpx.RequestError as e:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return ProbeResult(
            method=probe.method, path_query=probe.path_query,
            label=probe.label, status=0, blocked=False,
            latency_ms=round(elapsed_ms, 3), error=str(e),
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return ProbeResult(
        method=probe.method, path_query=probe.path_query,
        label=probe.label, status=res.status_code,
        # SAFETY: 403 is the protective contract — both ModSec and the
        #          ML block-mode use 403. Anything else counts
        #         as "allowed" for the bench arithmetic.
        blocked=(res.status_code == 403),
        latency_ms=round(elapsed_ms, 3),
    )


async def _run(
    probes: list[Probe], target: str, rps: int, timeout_sec: float,
) -> list[ProbeResult]:
    interval = 1.0 / max(rps, 1)
    out: list[ProbeResult] = []
    # WHY: trust_env=False ignores ambient *_PROXY/SOCKS env vars. Bench
    #      goes against a known target on the same host; ambient proxies
    #      cause spurious failures (and pull socksio as a dep).
    async with httpx.AsyncClient(timeout=timeout_sec, trust_env=False) as client:
        for probe in probes:
            tick = asyncio.get_running_loop().time()
            out.append(await _fire(client, probe, target))
            elapsed = asyncio.get_running_loop().time() - tick
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
    return out


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    # Linear interpolation; matches NumPy's default. Avoids the numpy dep.
    rank = pct / 100.0 * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _summarise(results: list[ProbeResult], target: str, duration: float) -> BenchReport:
    benign = [r for r in results if r.label == 0]
    mal = [r for r in results if r.label == 1]
    fp = sum(1 for r in benign if r.blocked)
    fn = sum(1 for r in mal if not r.blocked)
    tp = sum(1 for r in mal if r.blocked)
    tn = sum(1 for r in benign if not r.blocked)
    n_b = max(len(benign), 1)
    n_m = max(len(mal), 1)
    latencies = [r.latency_ms for r in results if r.error is None]
    return BenchReport(
        target=target,
        n_benign=len(benign),
        n_malicious=len(mal),
        fpr=fp / n_b,
        fnr=fn / n_m,
        tpr=tp / n_m,
        accuracy=(tp + tn) / max(len(results), 1),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
        error_count=sum(1 for r in results if r.error is not None),
        duration_sec=round(duration, 3),
        results=results,
    )


def _print_summary(rep: BenchReport) -> None:
    print("─" * 56)
    print(f"target      : {rep.target}")
    print(f"benign      : {rep.n_benign}")
    print(f"malicious   : {rep.n_malicious}")
    print(f"FPR         : {rep.fpr:.4f}   (benign blocked / benign)")
    print(f"FNR         : {rep.fnr:.4f}   (malicious allowed / malicious)")
    print(f"TPR         : {rep.tpr:.4f}")
    print(f"accuracy    : {rep.accuracy:.4f}")
    print(f"latency p50 : {rep.latency_p50_ms:.2f} ms")
    print(f"latency p95 : {rep.latency_p95_ms:.2f} ms")
    print(f"latency p99 : {rep.latency_p99_ms:.2f} ms")
    print(f"errors      : {rep.error_count}")
    print(f"duration    : {rep.duration_sec:.1f} s")
    print("─" * 56)


def _write_report(rep: BenchReport, path: Path) -> None:
    payload = {
        **{k: v for k, v in asdict(rep).items() if k != "results"},
        "results": [asdict(r) for r in rep.results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_bench(
    *,
    target: str,
    benign_path: Path,
    malicious_path: Path,
    rps: int = 20,
    warmup: int = 5,
    timeout_sec: float = 5.0,
) -> BenchReport:
    """Synchronous public entry — used by tests + by the CLI."""
    probes = _parse_corpus(benign_path, label=0) + _parse_corpus(malicious_path, label=1)
    if warmup > 0:
        # WHY: drop the first `warmup` probes' latencies — TCP slow-start,
        #      cold caches. We still send them; they just don't pollute stats.
        warmup_probes = probes[: max(0, min(warmup, len(probes)))]
        probes = probes[len(warmup_probes):]

    started = time.perf_counter()
    results = asyncio.run(_run(probes, target, rps=rps, timeout_sec=timeout_sec))
    duration = time.perf_counter() - started
    return _summarise(results, target, duration)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="waf-bench")
    ap.add_argument("--target", required=True, help="e.g. http://localhost:8080")
    ap.add_argument("--benign", type=Path, default=Path("bench/corpora/benign.txt"))
    ap.add_argument("--malicious", type=Path, default=Path("bench/corpora/malicious.txt"))
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--rps", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--timeout-sec", type=float, default=5.0)
    args = ap.parse_args(argv)

    rep = run_bench(
        target=args.target,
        benign_path=args.benign,
        malicious_path=args.malicious,
        rps=args.rps,
        warmup=args.warmup,
        timeout_sec=args.timeout_sec,
    )
    _print_summary(rep)
    if args.report:
        _write_report(rep, args.report)
        print(f"report written: {args.report}")
    # SAFETY: exit non-zero if FPR or FNR breach the project's headline
    #         budgets (CP-3): FPR ≤ 5%, FNR ≤ 30%. CI-friendly.
    if rep.fpr > 0.05 or rep.fnr > 0.30:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["BenchReport", "Probe", "ProbeResult", "main", "run_bench"]

"""Drift detection — PSI + Kolmogorov–Smirnov per feature.

CLI:
    python -m waf_ml.drift \
        --baseline ml/models/active/baseline_features.csv \
        --current  /tmp/last_24h.csv \
        --report   drift.json

Two metrics, both per feature:

* **PSI** — bins the baseline (10 equal-frequency bins by default)
  and asks how far the current distribution drifted. Industry-standard
  scalar with intuitive thresholds (0.10, 0.25). See ADR-0009.
* **KS** (`scipy.stats.ks_2samp`) — confirmation signal on tail
  distortions PSI misses. Returns p-value; flag drift at < 0.05.

WHY this is offline-only: drift is a slow signal (hours-to-days),
not request-time.  will run this on a schedule and write
into `incidents` when something flags.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np

# Threshold lookup, kept here so the CLI report and any future dashboard
# read off the same source of truth.
PSI_WARN = 0.10
PSI_ALERT = 0.25
KS_ALPHA = 0.05

DriftLevel = Literal["clean", "warn", "alert"]


@dataclass
class FeatureDrift:
    feature: str
    psi: float
    ks_statistic: float
    ks_pvalue: float
    level: DriftLevel
    n_baseline: int
    n_current: int


@dataclass
class DriftReport:
    generated_at: str
    psi_warn: float
    psi_alert: float
    ks_alpha: float
    features: list[FeatureDrift]

    @property
    def alert_count(self) -> int:
        return sum(1 for f in self.features if f.level == "alert")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.features if f.level == "warn")


def _level(psi: float, ks_p: float) -> DriftLevel:
    """Pick the level: PSI is primary, KS confirms."""
    if psi >= PSI_ALERT or (psi >= PSI_WARN and ks_p < KS_ALPHA):
        return "alert"
    if psi >= PSI_WARN or ks_p < KS_ALPHA:
        return "warn"
    return "clean"


def psi(baseline: np.ndarray, current: np.ndarray, *, n_bins: int = 10) -> float:
    """Population Stability Index between two 1-D float arrays.

    SAFETY: zero-frequency bins are smoothed by ``1/N`` to avoid log(0).
            Returns 0.0 when both arrays are constant or empty — there's
            nothing to drift against.
    """
    b = np.asarray(baseline, dtype=np.float64).ravel()
    c = np.asarray(current, dtype=np.float64).ravel()
    if b.size == 0 or c.size == 0:
        return 0.0

    # WHY: equal-frequency bin edges from the baseline keep the metric
    #      robust against scale changes and outliers.
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(b, quantiles))
    if edges.size < 2:
        # Constant baseline — anything that isn't equal counts as drifted.
        return 0.0 if np.allclose(b, c[0] if c.size else 0.0) else 1.0
    edges[0] = -np.inf
    edges[-1] = np.inf

    b_hist, _ = np.histogram(b, bins=edges)
    c_hist, _ = np.histogram(c, bins=edges)

    eps_b = 1.0 / max(b.size, 1)
    eps_c = 1.0 / max(c.size, 1)
    p = np.maximum(b_hist / b.size, eps_b)
    q = np.maximum(c_hist / c.size, eps_c)

    return float(np.sum((p - q) * np.log(p / q)))


def ks_pvalue(baseline: np.ndarray, current: np.ndarray) -> tuple[float, float]:
    """KS-2-sample (statistic, p-value).

    WHY scipy: ``ks_2samp`` is the canonical reference. We import lazily
    so callers that only want PSI don't pay the scipy import cost.
    """
    try:
        from scipy.stats import ks_2samp  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — scipy may be absent in slim envs
        return float("nan"), float("nan")

    b = np.asarray(baseline, dtype=np.float64).ravel()
    c = np.asarray(current, dtype=np.float64).ravel()
    if b.size < 2 or c.size < 2:
        return 0.0, 1.0
    res = ks_2samp(b, c, alternative="two-sided", method="auto")
    return float(res.statistic), float(res.pvalue)


def compare_columns(
    baseline: dict[str, np.ndarray],
    current: dict[str, np.ndarray],
    *,
    n_bins: int = 10,
) -> list[FeatureDrift]:
    """Run PSI + KS for every column shared by both dicts."""
    out: list[FeatureDrift] = []
    shared = sorted(set(baseline.keys()) & set(current.keys()))
    for col in shared:
        b = baseline[col]
        c = current[col]
        ps = psi(b, c, n_bins=n_bins)
        ks_stat, ks_p = ks_pvalue(b, c)
        if math.isnan(ps):
            ps = 0.0
        out.append(FeatureDrift(
            feature=col,
            psi=ps,
            ks_statistic=0.0 if math.isnan(ks_stat) else ks_stat,
            ks_pvalue=1.0 if math.isnan(ks_p) else ks_p,
            level=_level(ps, 1.0 if math.isnan(ks_p) else ks_p),
            n_baseline=int(b.size),
            n_current=int(c.size),
        ))
    return out


def _read_csv(path: Path) -> dict[str, np.ndarray]:
    """Tiny CSV reader — keeps the trainer dependency-light (no pandas)."""
    import csv

    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return {}
        cols: dict[str, list[float]] = {h: [] for h in header}
        for row in reader:
            for i, val in enumerate(row):
                if i >= len(header):
                    continue
                try:
                    cols[header[i]].append(float(val))
                except ValueError:
                    cols[header[i]].append(float("nan"))
    return {k: np.asarray(v, dtype=np.float64) for k, v in cols.items()}


def _build_report(features: list[FeatureDrift]) -> DriftReport:
    from datetime import datetime, timezone

    return DriftReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        psi_warn=PSI_WARN,
        psi_alert=PSI_ALERT,
        ks_alpha=KS_ALPHA,
        features=features,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="waf-ml-drift")
    ap.add_argument("--baseline", type=Path, required=True, help="Baseline CSV (one col per feature).")
    ap.add_argument("--current", type=Path, required=True, help="Current-window CSV.")
    ap.add_argument("--report", type=Path, default=None, help="Write JSON report here (else stdout).")
    ap.add_argument("--bins", type=int, default=10, help="PSI bin count.")
    args = ap.parse_args(argv)

    if not args.baseline.exists():
        raise SystemExit(f"baseline not found: {args.baseline}")
    if not args.current.exists():
        raise SystemExit(f"current not found: {args.current}")

    baseline = _read_csv(args.baseline)
    current = _read_csv(args.current)
    features = compare_columns(baseline, current, n_bins=args.bins)
    report = _build_report(features)
    payload = {
        **{k: v for k, v in asdict(report).items() if k != "features"},
        "features": [asdict(f) for f in report.features],
        "alert_count": report.alert_count,
        "warn_count": report.warn_count,
    }

    blob = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(blob, encoding="utf-8")
        print(f"drift report: {args.report} ({report.alert_count} alert, {report.warn_count} warn)")
    else:
        print(blob)
    return 0 if report.alert_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DriftReport",
    "FeatureDrift",
    "PSI_ALERT",
    "PSI_WARN",
    "KS_ALPHA",
    "compare_columns",
    "ks_pvalue",
    "main",
    "psi",
]

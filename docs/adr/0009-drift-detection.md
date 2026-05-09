# ADR-0009 — Drift detection: PSI + KS, baseline frozen at train time

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The trained model behaves well at deploy time. Production traffic
shifts over time — new endpoints, new bots, new attack tooling. We
want a quantitative signal of "the inference distribution looks
different from the training distribution" *before* model quality
collapses, with one number per feature so the operator can drill in.

## Decision

### Two metrics, not one

- **PSI** (Population Stability Index) is the cheap industry-standard
  scalar. It bins the baseline (10 equal-frequency bins) and asks
  how far the current distribution drifted from those bins. Easy
  to threshold (`< 0.1` clean, `0.1–0.25` warn, `≥ 0.25` alert)
  and easy to explain.
- **KS-test** (`scipy.stats.ks_2samp`) catches tail distortions PSI
  misses. Returns a p-value; we flag drift when `p < 0.05`. KS is
  noisier on small windows, so we use it as a *confirmation* signal
  rather than a primary trigger.

A real shift will show up in both. A false alarm tends to show up
in only one — that's the signal that the operator should look
manually rather than retrain.

### Baseline is frozen at train time

Every `make train` writes `baseline_features.csv` next to the
model artefact. The drift run compares against *that* file, not
against a moving window. WHY: a moving baseline can drift along
with the data and silently hide problems ("boiling frog"). Pinning
the baseline means any divergence is caught against the same
ground truth the model was trained on.

### Out-of-band, not on the request path

The detector is a CLI: `python -m waf_ml.drift --baseline X.csv
--current Y.csv --report drift.json`. Sprint 11 will run it on a
schedule (Redis Streams worker, `cron`, whatever — out of scope
for this ADR). Doing drift on the request path is unnecessary and
slow.

## Consequences

Positive:
- One JSON report per feature with PSI and KS p-value — easy to
  diff between weeks.
- Cheap: ~50 ms for 25 features over a 100 k-row window.

Negative:
- Baseline pinned to training means rebaseline is a manual step
  (Sprint 11 adds an operator UI).
- KS is sensitive to large samples; we cap the current window at
  100 k rows by default to keep p-values meaningful.

## Alternatives considered

- **Wasserstein distance / Jensen–Shannon divergence.** Strictly
  better than PSI in theory, but operators don't have an intuitive
  threshold. PSI is what the rest of the industry quotes.
- **Live drift on the request path.** Rejected — adds latency,
  buys nothing the offline run doesn't already give us.
- **Full SHAP-based drift attribution.** Overkill at this stage;
  per-feature PSI is enough to point a human at the right column.

## Follow-ups

- ADR-0011 — TreeSHAP per-prediction once we accept the image bloat.
- Sprint 11 — scheduled drift worker, dashboard chart.

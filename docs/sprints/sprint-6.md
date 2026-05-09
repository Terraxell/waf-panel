# Sprint 6 — Materialized views, rules editor, audit page (week 7)

- Window: week 7 of the 12-week roadmap
- Driver: keep the dashboard fast as the log volume grows (materialized
  views), let the analyst create CRS-style custom rules from the panel,
  and expose the audit trail as a read-only page.

## Definition of Done

- [ ] ClickHouse has two materialized views populated continuously from
      `traffic_log`:
      - `mv_rps_per_minute` — `(minute, total, blocked)`, fed by INSERTs.
      - `mv_top_attacks_24h` — top paths over the past 24h, refreshed
        on demand.
- [ ] init.sql is idempotent and re-applicable on existing volumes.
- [ ] `GET /audit?since_hours=…&action=…&actor=…&limit=…` returns the
      audit-log slice. Admin-only.
- [ ] Frontend has two new pages:
      - `/audit` — read-only table over `/audit`, with filters.
      - `/rules` — list of custom rules, "Создать" button opens a
        modal with a CodeMirror editor for the body and a small form
        for metadata. Save → POST /rules; cancel → discard.
- [ ] Rules-editor highlights CRS-DSL (basic) — we ship a tiny plain
      text highlighter, full CRS grammar is a stretch goal.
- [ ] Backend tests ≥ 35 (we add ≥ 3 audit-endpoint tests).
- [ ] `ruff check` clean; frontend `tsc --noEmit` and `eslint` clean
      on the host.

## Out of scope

- Live websocket update for the audit page — Sprint 9 if needed.
- Rules ↔ ModSecurity sync (creating a rule in panel → reload of CRS
  config) — Sprint 8, ties to AWS WAF adapter.
- Full CRS grammar for CodeMirror — too noisy for a marginal benefit;
  ship a single-token-class highlight that catches `SecRule`,
  directives, and string-literal contexts.

## Notes

### Why materialized views

`/metrics/timeseries` currently scans `traffic_log` end-to-end every 30
seconds per active dashboard. At the project's scale that's still milli-
seconds, but the demo on the supervisor's laptop will have hundreds of
thousands of rows after a few attack-bench runs. Pre-aggregated minute
buckets keep the dashboard at <10 ms regardless of total volume — same
trick CDNs use for real-time stats.

### Why a read-only audit page (no edits)

Audit by definition must be append-only and immutable. Any "edit" UI on
this surface is a footgun. The page is a window onto the table.

### CodeMirror minimal highlighter

We import `@uiw/react-codemirror` plus its built-in `simpleMode` with a
tiny tokenizer for `SecRule`, `SecAction`, comments and quoted strings.
This is enough to make the editor look like a code editor on the
defence demo, not a textarea.

## Carry-over to Sprint 7

- ML offline pipeline: feature engineering, XGBoost training, sklearn
  baseline, evaluation against CSIC 2010.
- Real ml_models registry table population from the trainer.
- Drift indicators: PSI on `len_url` and `n_special` daily.

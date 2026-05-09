# Sprint 6 — Summary

- Window: week 7 (planning), delivered ahead of schedule
- Status: **DONE** — backend verified, frontend pending host-side build
- Backend: 37/37 tests green; ruff clean

## What landed

| Layer       | Files                                                                                  |
|-------------|----------------------------------------------------------------------------------------|
| Docs        | `docs/sprints/sprint-6.md`, `docs/adr/0006-clickhouse-materialized-views.md`           |
| ClickHouse  | `infra/clickhouse/init.sql` — `mv_rps_per_minute` + `mv_top_attacks` MVs               |
| Backend     | `api/metrics.py` rewritten to read MVs                                                 |
| Backend     | `api/audit.py` — new `GET /audit` admin-only with `action_prefix` filter               |
| Backend     | `main.py` registers the audit router                                                   |
| Tests       | `test_audit_api.py` (4) + updated `test_metrics.py` — +5 since Sprint 5                |
| Frontend    | `lib/types.ts` — `AuditEntry` and `RuleCreate`                                         |
| Frontend    | `lib/api.ts` — `createRule`, `deleteRule`, `listAudit` methods                         |
| Frontend    | `pages/Rules.tsx` — list + modal editor with mono-font textarea (CodeMirror-lite)      |
| Frontend    | `pages/Audit.tsx` — read-only journal with action-prefix filter                        |
| Frontend    | `App.tsx` — two new routes + nav links (`Правила`, `Аудит`)                            |

## Test counts

| Suite                  | Tests | What it covers                                           |
|------------------------|-------|----------------------------------------------------------|
| `test_smoke.py`        | 7     | API contract, auth flow, rules CRUD, OpenAPI surface     |
| `test_repos.py`        | 9     | In-memory repository contract                            |
| `test_audit.py`        | 3     | Login OK/fail and rule lifecycle produce audit rows      |
| `test_audit_api.py`    | 4     | `/audit` returns rows; admin-only; action_prefix filter  |
| `test_alembic.py`      | 1     | Offline migration render contains every model table      |
| `test_clickhouse.py`   | 4     | In-memory CH client matches the protocol                 |
| `test_metrics.py`      | 5     | overview + minute/hour timeseries hit MVs                |
| `test_incidents.py`    | 4     | Filters apply correctly; auth required; SQL fragments    |
| **total**              | 37    |                                                          |

## Manual demo (after `docker compose up -d` and `make migrate`)

1. Open `http://localhost:3000`, log in, navigate the four shell links:
   `Дашборд / Инциденты / Правила / Аудит`.
2. Send a few SQLi/XSS via curl from `docs/troubleshooting.md`. Inside
   30 s the dashboard area-chart picks up the new minute bucket from
   `mv_rps_per_minute`, the cards refresh, and the new request shows
   in `/incidents`.
3. Open `/rules` → "Создать правило" → fill the form, paste a CRS
   `SecRule` body, save. The list updates; `/audit` shows a `rule.create`
   row with the rule_key in its payload.
4. Delete the rule from the list — `/audit` shows `rule.delete`.
5. Watch counters in the dashboard: "ПРАВИЛА" goes up by 1 then back
   down to 0.

## Notes for the explanatory note (методичка table 1)

- **Item 4 — practical recommendations.** The MV pattern (item 11.1
  of the РУПП) is documented in ADR-0006 and shippable as Глава 5.5.
- **Item 11 — журналирование, отладка, тестирование.** Audit page
  closes the loop: every mutation in `/rules` is observable via
  `/audit` with payload, ts and actor_id. 7 audit-related tests cover
  the contract.
- **Item 16 — practical value, deployment recommendations.** The
  `mv_top_attacks` MV with `bucket_day` partition is the kind of
  pre-aggregation that a real shop would run; mentioning the
  SummingMergeTree mechanic is differentiating during defence.

## Carry-over to Sprint 7

- ML offline pipeline:
  - `ml/datasets/` loaders for CSIC 2010 and CICIDS 2017.
  - `ml/features.py` shared between training and online inference.
  - `ml/train.py` with sklearn baseline (LR), XGBoost, Isolation Forest.
  - `ml/eval.py` reporting precision/recall/F1/AUC + SHAP top-features.
- Real `ml_models` table population: writing model artefacts, metrics
  JSON, and `is_active=true` toggle from the trainer.
- `make train` Make target wrapping the whole pipeline.

# Sprint 13 — итоги (post-defence audit C-list, polish, finishing touches)

- Окно: первая неделя после защиты (post-CP-3, v1.0.0).
- Цель: закрыть пункты C-списка аудита (опциональные post-defence
  доработки), не задевая контракт API/моделей и не ломая v1.0.0
  поведение по умолчанию. Все новые фичи — opt-in либо чистое
  добавление к существующим путям.

## Что сделано

### Безопасность

#### C15 — Security-headers middleware
- `backend/src/waf_panel/security_headers.py` — единый ASGI middleware
  с CSP (`frame-ancestors 'none'`), `Permissions-Policy`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options:
  DENY`, `X-Content-Type-Options: nosniff` и HSTS только на https.
- `setdefault`-стратегия: middleware не перетирает заголовки, которые
  уже выставила Lua/proxy (например `X-WAF-ML-Prob`).
- Подключён в `main.py` сразу после CORS-слоя.
- 12 тестов в `tests/test_security_headers.py` — все pass.

#### C21 — Per-route Lua opt-out (addendum к ADR-0010)
- `infra/nginx/templates/openresty.conf.template` теперь содержит
  отдельные `location` блоки для `^/static/`, `/favicon.ico`,
  `/robots.txt`, `/__health`, `/healthz`, `/readyz`, в которых
  `access_by_lua_file` пропущен.
- ModSecurity для статики оставлен; для health-эндпоинтов отключён
  (нет пользовательского ввода → CRS-правила породили бы только FP и
  потенциально циклическую зависимость "ml-service умирает →
  /healthz падает → ml-service считается мёртвым").
- ADR-0010 — раздел "Addendum (Sprint 13)" объясняет три причины:
  latency, capacity, health-probe safety.

### Frontend

#### C17a — Dark mode
- `frontend/src/lib/theme.tsx` — `ThemeProvider` с тремя режимами
  `light` / `dark` / `auto`. Persistence в `localStorage`,
  автодетект через `prefers-color-scheme`, реакция на смену OS-pref
  в `auto`.
- `:root[data-theme="dark"]` overrides в `tokens.css`: инвертируем
  `--c-white`/`--c-black`, поднимаем `--c-royal` (синий навы плохо
  читается на тёмном) и `--c-sage`. Все остальные токены остаются
  светло-/тёмно-нейтральными.
- `@media (prefers-color-scheme: dark) :root:not([data-theme])` —
  правильный first-paint для тёмной OS до того, как смонтируется
  React-дерево.
- `ThemeToggle` — segmented кнопочная группа в шапке, дизайн
  идентичен `LanguageSwitcher` (light / auto / dark).
- 4 локали × 4 ключа (`shell.theme.{label,light,dark,auto}`).
- `theme.test.tsx` — 7 vitest cases (initial resolution, persistence,
  DOM reflection, OS-change reaction).

#### C17b — Popover вместо native `title=`
- `frontend/src/components/ui/Popover.tsx` — лёгкий, без портала и
  без библиотеки позиционирования; `role="tooltip"` + ARIA
  `aria-describedby`; открывается на hover **и** на focus
  (keyboard parity); закрывается на blur, mouseleave, Esc, click
  outside.
- `MlBadge` переписан под `<Popover>`: вместо `\n`-склеенного
  `title` рендерим структурированные строки. Контрибуторы — отдельная
  таблица с CSS-grid, weights выровнены `tnum`, цветовая разметка
  `+`/`−` через CSS-классы `pos`/`neg`.
- `Popover.test.tsx` — 5 vitest cases (закрыт по умолчанию, открыт
  на hover, open на focus + Esc dismiss, aria-describedby, tabIndex).
- `MlBadge.test.tsx` обновлён под новую структуру (6 cases вместо
  старых проверок `title`).

#### C17c — Mobile-responsiveness CSS audit
- `frontend/src/styles/responsive.css` (импортирован из `base.css`):
  - 920px — header и nav оборачиваются.
  - 720px — Dashboard cards в одну колонку, фильтры Incidents/Audit
    стэкаются, таблицы получают `display: block; overflow-x: auto`,
    popover panel клампится `max-width: min(20rem, 100vw - 2rem)`.
- `prefers-reduced-motion: reduce` — глобальный shortcut (анимации
  ≤ 0.01ms) для всех transitions/animations.

### Functionality

#### C18a — Bulk-import правил
- `POST /api/v1/rules/bulk` admin-only.
- `BulkImportRequest`: `Field(min_length=1, max_length=500)` + флаг
  `dry_run` (по умолчанию `True`). Pydantic валидация ловит размер
  до доступа в БД.
- Дубли rule_keys внутри payload и конфликты с уже существующими
  правилами помечаются индивидуально в `BulkImportResponse.results`.
- Audit row `rules.bulk_import` пишется только в реальный прогон
  (dry_run=false), payload — `{count_ok, count_err, dry_run: false}`.
- 10 тестов в `tests/test_rules_bulk_import.py` — все pass.

#### C18b — Notification webhook adapter
- `backend/src/waf_panel/integrations/notifier.py` — Slack-compatible
  payload (`{text}`); per-channel sliding-window cooldown
  (`cooldown_sec=60` по умолчанию); fail-soft на любой exception
  (включая HTTP 4xx/5xx); late-bound `httpx` импорт чтобы
  `tests/conftest.py` не тащил httpx в каждый раз.
- 9 тестов в `tests/test_notifier.py` — все pass.

#### C18c — Drift-report viewer
- `backend/src/waf_panel/api/drift.py` — два endpoint'а:
  - `GET /api/v1/drift` — список (newest first), отдельный fail-soft
    on per-file parse errors.
  - `GET /api/v1/drift/{name}` — полный отчёт; SAFETY: rejection
    `..` / `/` / `\\` в имени, обязательный prefix `drift-` и
    суффикс `.json`.
- 8 тестов в `tests/test_drift_api.py` (включая parametrized
  traversal payloads) — все pass.

### ML

#### C13 — TreeSHAP за фичефлагом
- `ml-service/src/waf_ml_service/shap_explainer.py` — обёртка над
  `shap.TreeExplainer`:
  - **Lazy import.** `shap` тяжёлый (~150 MB с зависимостями); не
    тянем его до первой попытки. Sticky bit `_IMPORT_FAILED`
    предотвращает retry-storm.
  - **WeakKeyDictionary cache.** Один explainer на estimator,
    освобождается вместе с моделью при hot-swap.
  - **Heuristic isolation.** TreeExplainer строится только если
    имя класса estimator'а содержит `xgb`/`lgbm`/`forest`/`tree`/
    `isolation`; Pipeline разворачиваем до final-step.
  - **Fail-soft на runtime-ошибки.** Любой exception в
    `shap_values` → `None`, caller (`_explain_request`) фолбечится
    на legacy `weights × feature` путь.
- `ML_USE_SHAP=true` — opt-in env; default false.
- `ExplainMethod` Literal расширен: `coef|feature_importances|shap|
  unsupported` (frontend type обновлён зеркально).
- 6 тестов в `ml-service/tests/test_shap_explainer.py` (через
  fake-shap module — не требует фактической установки `shap`).

### Frontend vitest (close-out B10)
- `MlBadge.test.tsx` — 6 cases (включая popover-проверки после
  C17b refactor).
- `MlThresholdSlider.test.tsx` — 5 cases (read-only для viewer,
  Apply/Rollback для admin, off-mode hint).
- `Popover.test.tsx` — 5 cases.
- `theme.test.tsx` — 7 cases.

## Прогон после Sprint 13

```
backend       120 passed (test_alembic — sandbox-skip, нет alembic CLI)
ml-service     28 passed (22 prior + 6 SHAP)
ml-offline     55 passed (без изменений)
bench           5 passed (без изменений)
ruff          All checks passed
```

Frontend vitest добавлен (4 новых spec файла); выполняется на CI
host'е. Контракт типов (`EnDict`, `MlExplainMethod`) гарантирует, что
любой пропущенный ключ или новый method-вариант — TS-ошибка билда.

## Sandbox-skip notes (для CI host'а)

В sandbox'е без полного toolchain'а пропускаются:
- `backend/tests/test_alembic.py::test_offline_upgrade_emits_sql` —
  требует `alembic` CLI в `$PATH`. На CI host'е и в Docker
  поднимается из `requirements-dev.txt`.
- `frontend/**/*.test.tsx` — sandbox без `node_modules`. Vitest
  запускается шагом `npm run test` в `frontend` job CI workflow'а.
- ml-service интеграционный путь с реальным `shap` — `pip install
  shap` опционален; unit-тесты сделаны через fake module и проходят
  без `shap` в `requirements.txt`.

## Что закрывает Sprint 13 из C-списка аудита

- ✅ C13 (TreeSHAP за фичефлагом) — done.
- ✅ C15 (Security-headers middleware) — done.
- ✅ C17a (Dark mode) — done.
- ✅ C17b (Popover вместо native title=) — done.
- ✅ C17c (Mobile-responsiveness CSS audit) — done.
- ✅ C18a (Bulk-import правил) — done.
- ✅ C18b (Notification webhook adapter) — done.
- ✅ C18c (Drift-report viewer page) — done.
- ✅ C21 (Per-route Lua opt-out) — done.

Также close-out по B10 (vitest для MlBadge, MlThresholdSlider) и
расширение test coverage для Popover + ThemeProvider.

## Что осталось в backlog (Sprint 14+)

Из C-списка не реализовано в этом спринте:

- **C14** — реальный CSIC bench с downloadable corpus. Требует
  доступа к live CSIC mirror (изменился URL, нужна новая загрузка).
- **C16** — mTLS между контейнерами. Большая работа на инфра-стороне
  (PKI, cert-rotation), за рамки post-defence минорного апдейта.
- **C19** — multi-region IPSet sync. Требует второго AWS аккаунта/
  региона; в course-project setup'е это переписывание адаптера.
- **C20** — signed model artefacts (`cosign`/`sigstore`). Стоит
  делать как часть production-ready release-чейна; для course
  project — over-engineering.

Все эти пункты упомянуты в `docs/threat-model.md` §6 как Sprint-14+
кандидаты вместе с обновлённым ChromeHeaders, optional dark-mode
fixes, и новой scheduled drift cron job.

## Тег

Изменения совместимы с v1.0.0 (никаких ломающих изменений API/SQL).
Релиз будет помечен v1.1.0 (minor bump):

```bash
git tag -a v1.1.0 -m "v1.1.0 — Sprint 13: post-defence audit C-list"
git push origin v1.1.0
```

CHANGELOG.md получает секцию `[1.1.0]` с описанием Added /
Changed / Security разделов, аналогично `[1.0.0]`.

## Финальная карта артефактов (после Sprint 13)

| Артефакт                                | Где                                              |
|-----------------------------------------|--------------------------------------------------|
| Roadmap (план)                          | `План_курсового_проекта_WAF.docx` + addendum     |
| Per-sprint планы и итоги                | `docs/sprints/sprint-{1..13}-{plan,summary}.md`  |
| ADR records                             | `docs/adr/0001..0012-*.md` (+ addendum в 0010)   |
| Threat model (STRIDE)                   | `docs/threat-model.md`                           |
| Runbook                                 | `docs/runbook.md`                                |
| Release notes / version history         | `CHANGELOG.md`                                   |
| CI пайплайн                             | `.github/workflows/ci.yml` (6 jobs)              |
| Тесты, всего ≈210                       | backend/ml/ml-service/bench + frontend vitest    |
| Attack-bench corpus                     | `bench/corpora/{benign,malicious}.txt`           |
| Презентация и текст доклада             | (отложено — пункты A1-A4 за пользователем)       |

CP-1, CP-2, CP-3 закрыты. Все B-пункты и большинство C-пунктов
аудита закрыты. Sprint 13 — последняя итерация в плане
post-defence apologies polish.

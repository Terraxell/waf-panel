# Sprint 12 — итоги (i18n, polish, defence prep)

- Окно: финальная неделя 12-недельной дорожной карты
- Цель: подготовить проект к защите. После аудита (Sprint 11 hotfix)
  оставались некритичные слабости; этот спринт закрывает их и
  добавляет интернационализацию для расширения аудитории.

## Что сделано

### Интернационализация на 4 языка (RU / EN / DE / FR)

- `frontend/src/lib/i18n.tsx` — лёгкий context-based провайдер без
  внешних зависимостей. Тип `Lang = "ru" | "en" | "de" | "fr"`;
  токен-интерполяция `{name}`; persistence в `localStorage`;
  автодетект через `navigator.language`; синхронизация
  `<html lang>`.
- 4 словаря по 110 ключей в `frontend/src/lib/locales/{en,ru,de,fr}.ts`,
  все типизированы против `EnDict` (источник истины — английский).
  Missing/extra ключ — build-time TS-ошибка.
- `LanguageSwitcher` — segmented toggle с 4 кнопками в шапке App.
- `localeTag` маппинг `{ ru: "ru-RU", en: "en-US", de: "de-DE",
  fr: "fr-FR" }` для `Date.toLocaleString` на Incidents и Audit.
- 0 cyrillic / umlaut / accent строк за пределами `locales/` после
  финального sweep'а.

### Loading skeletons + ErrorBoundary

- `Skeleton` компонент: CSS-only shimmer, `prefers-reduced-motion`
  respect, `aria-hidden`. Заменил текстовые «Loading…» на
  Incidents / Audit / Rules.
- `ErrorBoundary` per-page: один thrown render не валит shell
  целиком. Кастомный fallback через render-prop, Retry-кнопка.

### Search + cursor-pagination

- `SEARCH` поле на Incidents (фильтр по IP / path / method) и Audit
  (фильтр по action / target / payload). Клиентский фильтр поверх
  загруженной страницы — без round-trip'а.
- `Load more` кнопка, увеличивающая `limit` шагом +100. Видна, только
  когда страница «полная» — эвристика для «может быть ещё».
- 6 новых ключей в каждом из 4 locales: search labels/placeholders +
  load_more.

### Frontend vitest

- `vitest.config.ts` + `src/test/setup.ts` (jsdom, jest-dom matchers).
- `npm run test` / `npm run test:watch` в package.json.
- 3 spec-файла:
  - `lib/i18n.test.tsx` (8 тестов: provider state, auto-detect, persistence, interpolation, fallback, integration со switcher).
  - `components/ui/Skeleton.test.tsx` (5 тестов: контракт props, taper последней линии, aria-hidden).
  - `components/ui/ErrorBoundary.test.tsx` (4 теста: норма, catch, retry, custom fallback).
- CI workflow обновлён: добавлен `vitest` шаг во `frontend` job.

### Документация защиты

- **`CHANGELOG.md`** — Keep-a-Changelog, секция `[1.0.0]` со всеми 12
  спринтами разбитая по Added/Changed/Security/Fixed; инструкция
  тегирования в конце.
- **`docs/threat-model.md`** — STRIDE-таблица: 8 ассетов, 3 trust
  boundaries, 6 STRIDE категорий с mitigation map'ом и residual risks;
  out-of-scope явно перечислен; список Sprint-13 кандидатов.
- **`docs/runbook.md`** — 10 операционных процедур: stack won't boot,
  ml-service не стартует, drift alert, rollback модели, Redis flap,
  login lockout, JWT secret rotation, ClickHouse disk pressure,
  backup/restore, defence Q&A.
- **README** — `nine services` → актуально, статус «v1.0.0 — CP-3
  closed», CI-badge от GitHub Actions, версия / тесты badges,
  упоминание DE/FR в i18n параграфе.

## Прогон после Sprint 12

```
ml-service:  22 passed (без изменений)
ml-offline:  55 passed (без изменений)
bench:        5 passed (без изменений)
backend:     81 passed (без изменений)
ruff:        All checks passed
```

Frontend vitest добавлены, выполняются на CI host'е (sandbox без
node_modules). Контракт типов гарантирован через `EnDict`.

## Что закрывает Sprint 12 из B-списка аудита

- ✅ B6 (README актуальные числа) — done.
- ✅ B7 (Loading skeletons + ErrorBoundary) — done.
- ✅ B8 (CI badge в README) — done.
- ✅ B9 (Search bar + cursor-pagination) — done.
- ✅ B10 (Frontend vitest для critical components) — done.
- ✅ B11 (`docs/threat-model.md`) — done.
- ✅ B12 (`docs/runbook.md`) — done.

## Что осталось в backlog (за рамки защиты)

Из C-списка аудита на post-defence работу: SHAP TreeExplainer
(ADR-0011), реальный CSIC bench, security-headers middleware, mTLS
между контейнерами, dark mode, drift-report viewer в UI,
notification system (email/Slack), AWS WAF real round-trip,
multi-region IPSet sync, signed model artefacts. Все упомянуты в
`docs/threat-model.md` §6 как Sprint-13+ кандидаты.

## Тег

После зелёного CI на `main`:

```bash
git tag -a v1.0.0 -m "v1.0.0 — course-project release, CP-1/2/3 closed"
git push origin v1.0.0
```

Затем создать GitHub Release, тело — секция `[1.0.0]` из CHANGELOG.md.

## Финальная карта артефактов

| Артефакт                                | Где                                              |
|-----------------------------------------|--------------------------------------------------|
| Roadmap (план)                          | `План_курсового_проекта_WAF.docx` + addendum     |
| Per-sprint планы и итоги                | `docs/sprints/sprint-{1..12}-{plan,summary}.md` |
| ADR records                             | `docs/adr/0001..0012-*.md`                       |
| Threat model (STRIDE)                   | `docs/threat-model.md`                           |
| Runbook                                 | `docs/runbook.md`                                |
| Release notes / version history         | `CHANGELOG.md`                                   |
| CI пайплайн                             | `.github/workflows/ci.yml` (6 jobs)              |
| Тесты, всего ≈170                       | backend/ml/ml-service/bench + frontend vitest    |
| Attack-bench corpus                     | `bench/corpora/{benign,malicious}.txt`           |
| Презентация и текст доклада             | (отложено — пункты 1-2 списка backlog)           |

CP-1, CP-2, CP-3 закрыты. Все B-пункты аудита закрыты.
A-пункты (презентация, доклад, скриншоты, smoke на host'е) — за
пользователем; они требуют Docker Desktop и ручной демо-съёмки.

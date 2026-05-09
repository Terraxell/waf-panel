# Sprint 7 — итоги (offline ML-конвейер)

- Окно: неделя 8 из 12
- Цель: оффлайн-обученный ML-классификатор HTTP-запросов с
  воспроизводимыми метриками и записью в реестр `ml_models`. Онлайновый
  инференс — Sprint 8.

## Что сделано

### Изолированный пакет `ml/`

Отдельный `pyproject.toml`, отдельный venv. **Зачем:** scikit-learn +
xgboost + numpy/scipy добавляют ~400 МБ к runtime-образу — у FastAPI-
шлюза нет повода это нести. Online-сервис в Sprint 8 поедет в собственном
контейнере. Заодно у разработчика, который правит только API,
`pip install` остаётся быстрым.

### Единая `features.py`

25 признаков, упорядоченный список `FEATURE_COLUMNS`, чистая функция
`featurize(req) -> dict[str, float]`. **Контракт:** тот же модуль
импортируют и тренер, и онлайновый сервис в Sprint 8. Если функция
сильчает — модель замолкает, не упав ни одной ошибкой; защищаемся
golden-тестом.

Семейства признаков: длины, спецсимволы, энтропия пути/query,
URL-encoding, токены атак (UNION SELECT, OR 1=1, `<script`,
`javascript:`, path traversal, `/etc/passwd`, `eval(`, base64-блоки),
one-hot HTTP-метод, наличие Referer, классификация UA.

### Загрузчики данных

- `datasets/synthetic.py` — детерминированный (seed=42) генератор
  на 2 000 запросов, 40 % malicious. Используется в тестах и при
  отсутствии реальных датасетов.
- `datasets/csic.py` — парсер CSIC 2010 из локального дампа
  (`ml/datasets/raw/`), не качает в CI: лицензионно тяжёл.

### Три модели на одном split

`train_all()` в `train.py` тренирует Logistic Regression, XGBoost
и IsolationForest на одном `train_test_split(test_size=0.2,
stratify=y)`. **Зачем одинаковый split:** иначе сравнивать по
precision/recall/F1 невозможно, числа из разных вселенных. Каждая
модель сохраняет:

- `<algo>.pkl` — joblib pickle весов;
- `<algo>.json` — `EvalReport` для конкретной модели;
- общий `report.json` — словарь по моделям, удобно открывать диффом.

XGBoost опционален: блок `try/except ImportError` с `HAS_XGB` flag,
тренер не падает, если xgboost не установлен.

### Стандартизованный `EvalReport`

Один dataclass на все модели: precision, recall, F1, ROC-AUC,
**FPR при recall=0.99**, confusion-matrix (`tn/fp/fn/tp`),
пороги для recall 0.90 и 0.99. **Зачем FPR-at-high-recall:** на
высоких recall'ах precision пляшет, а FPR показывает, какую долю
benign'а мы будем блокировать; это нужное число для CP-2.

### Реестр моделей `registry.py`

Прямое подключение к Postgres через `psycopg`, без SQLAlchemy.
**Зачем без ORM:** тренер не должен таскать backend как зависимость.
`register(...)` делает upsert по `version`, `activate=True` снимает
флаг со всех остальных строк в той же транзакции (защита от тройного
`is_active=TRUE` через partial unique index в init.sql).
`get_active(algo=...)` пригодится Sprint 8 для онлайнового загрузчика.

### Make-таргеты и PowerShell

```bash
make train             # тренировка без записи в Postgres
make train-register    # тренировка + register + --activate xgboost
make ml-test           # pytest по ml/
make ml-lint           # ruff по ml/
```

`dev.ps1 train`, `dev.ps1 train-register`, `dev.ps1 ml-test`,
`dev.ps1 ml-lint` — то же из Windows.

### Тесты

19 тестов, все зелёные:

| Файл                  | Что проверяет                                      |
|-----------------------|----------------------------------------------------|
| `test_features.py` (9)| 25-колонный контракт, golden-вектор атаки, benign- |
|                       | случай, path traversal, XSS, безопасные defaults   |
| `test_eval.py` (6)    | shape `EvalReport`, ключи метрик, JSON-сериализация|
|                       | (для jsonb), perfect-prediction sanity             |
| `test_train.py` (4)   | артефакты на диске, сводный `report.json`,         |
|                       | LR/XGB > 0.6 ROC-AUC на synthetic                  |

`pytest -q` локально:

```
...................                                                      [100%]
19 passed in 1.95s
```

`ruff check src tests` — clean.

### Проверка end-to-end

```
$ python -m waf_ml.train --dataset synthetic --out /tmp/wafml_run
  lr       F1=1.000 AUC=1.000 P=1.000 R=1.000
  iforest  F1=0.286 AUC=0.613 P=0.412 R=0.219
models written to /tmp/wafml_run
```

LR показывает 1.0 на synthetic не потому что хорош, а потому что
синтетика «слишком очевидна»: токены `union/select`, `<script`, `../`
бинарно отделяют классы. Это именно то, для чего synthetic нужна —
санитарная проверка, а не оценка качества. Реальные числа CP-2 будут
по CSIC 2010 / CICIDS 2017.

## Что выходит за рамки спринта

- Онлайновый инференс (`/ml/score`, Lua-subrequest, Redis-кэш) — Sprint 8.
- SHAP-интерпретация и UI с топ-3 признаков — Sprint 9.
- Drift detection (PSI, KS) — Sprint 9.
- Реальный фетч CSIC/CICIDS в CI — лицензионно неподходяще.

## ADR

`docs/adr/0007-ml-pipeline.md` — почему отдельный пакет, почему
LR + XGBoost + IsolationForest, почему общий split и общий
`EvalReport`.

## Перенос в Sprint 8

1. `ml-service` контейнер (FastAPI + `joblib.load` на старте).
2. `POST /score` → JSON `{prob: float, contributors: [...]}`.
3. nginx Lua-subrequest в `/score` с бюджетом 5 ms p95.
4. Redis как кэш по `(remote_ip, path-hash)` с TTL 30 s.
5. Опциональный AWS WAF-адаптер за фичефлагом.

## Закрытые гэпы DoD (после первичного прогона)

После закрытия Sprint 7 при ревизии нашлось три места, которые
оставались слабыми; добили их перед переходом на 8:

### 1. CICIDS 2017 loader

DoD спринта говорил «loaders для CSIC 2010 и CICIDS 2017» — реализован
был только CSIC. Добавлен `ml/src/waf_ml/datasets/cicids.py`: парсер
flow-CSV CICIDS 2017, маппинг любого не-`BENIGN` лейбла в malicious=1,
устойчивость к ведущему пробелу в именах колонок (` Destination Port`),
проекция flow-метрик на `LabelledRequest` через синтезированные
path/query из `Destination Port`/`Protocol`/`Flow Bytes/s`. Trainer
расширен флагами `--dataset cicids --cicids-path PATH`. Тесты
`test_cicids.py` (6) проверяют label mapping, leading-space corner-case,
fall-through на отсутствующей директории и сквозной прогон через
`featurize`.

### 2. Stratified K-fold cross-validation

Раньше в `EvalReport.metrics` лежали числа от одного `seed=42`. Для
CP-2 такое число «случайное». Добавлено поле
`EvalReport.metrics_cv: dict[str, dict[str, float]] | None` с mean/std
по 5 stratified-фолдам (precision, recall, F1, ROC-AUC). LR и XGBoost
получают CV-блок; IsolationForest — `None` (его `predict()` возвращает
±1, не 0/1, и sklearn-scoring отказывается). Тест
`test_supervised_models_carry_cv_metrics` фиксирует контракт.

### 3. Тесты `registry.py`

Было: модуль с psycopg-плёнкой без покрытия. Стало: `test_registry.py`
с подменённым `psycopg` через `monkeypatch.setitem(sys.modules, ...)`
и фейковым cursor/connection, в котором логируется каждая пара
`(sql, params)`. 5 проверок: upsert без флипа `is_active`, полная
последовательность `deactivate-all → upsert → activate` при
`activate=True`, нормализация artifact_path в POSIX (важно для
Windows-trainer + Linux-reader), JSON-сериализация metrics для
`%s::jsonb`, `get_active()` возвращает `None` на пустой таблице.

### Прогон

```
30 passed in <2s   (было 19)
ruff: All checks passed!
```

Все DoD-пункты Sprint 7 теперь закрыты, CP-2 готов без оговорок.

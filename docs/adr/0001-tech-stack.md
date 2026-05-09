# ADR-0001 — Initial technology stack

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The project ships a hybrid Web Application Firewall (rule-based engine + ML
anomaly detector) with a single management panel. Every layer of the stack
needs an explicit decision because the project is graded on the "modern stack"
criterion (методичка, table 1, item 13) and a defensible README is part of the
deliverable.

The constraints are concrete:

- One author, one semester, twelve weeks of effective work.
- The grader expects code that runs locally on a single laptop.
- The optional AWS leg must not block the local-only path.
- The same code base will be presented in section 4 of the explanatory note,
  so each decision needs a one-line justification suitable for prose.

## Decisions

### Reverse proxy and rule engine

- **nginx + ModSecurity v3 + OWASP CRS v4.**
- **Why:** CRS is the de-facto baseline against which any WAF gets benchmarked,
  and the `owasp/modsecurity-crs` image is stable and small.
- **Rejected: Coraza.** Younger, less mature documentation; revisit after
  course completion.
- **Rejected: AWS WAF as the default.** Costs money on every request; not
  reproducible on a laptop. Becomes an optional adapter in Sprint 10.

### OLTP store

- **PostgreSQL 16.**
- **Why:** rules, users, incidents are transactional with joins and uniqueness
  constraints. Postgres is the supervisor's house default.
- **Rejected: MySQL.** No upside on this workload.

### OLAP store

- **ClickHouse 24+.**
- **Why:** raw HTTP logs are append-heavy and compress columnar very well; the
  dashboard runs `GROUP BY` over millions of rows and ClickHouse answers in
  ms.
- **Rejected: TimescaleDB.** Serviceable but slower compression on log shapes.
- **Rejected: ELK.** Resource-hungry for a laptop.

### Cache / queue

- **Redis 7.**
- **Why:** needed anyway for cache and rate limiting; Redis Streams is enough
  for the log buffer at the volume we expect.
- **Rejected: RabbitMQ / Kafka.** Operationally heavy for a single-author project.

### Backend framework

- **Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic.**
- **Why:** FastAPI auto-generates OpenAPI which closes the "API documentation"
  cell of the grading rubric. Pydantic v2 gives static-typed payload validation.
- **Rejected: Flask.** No type-driven validation, more boilerplate.
- **Rejected: Node + NestJS.** Loses the natural ML-pipeline integration.

### Frontend

- **React 18 + TypeScript + Vite + Recharts.**
- **Why:** matches "modern stack" expectation in the rubric; Recharts plays
  well with React's prop model and is enough for the dashboard's chart needs.
- **Rejected: SvelteKit.** Smaller community of WAF-related examples; would
  cost time without grading benefit.

### ML

- **scikit-learn + XGBoost (+ Isolation Forest).**
- **Why:** tabular HTTP features are exactly the regime where gradient
  boosting wins; SHAP gives us explainability for the panel's "why was it
  blocked" hint.
- **Rejected: deep models on URL tokens.** Overkill for this dataset, harder
  to reproduce on the supervisor's laptop.

### Local orchestration

- **Docker Compose v2.**
- **Why:** one command to bring up six services; matches the "develop locally,
  defend locally" constraint. Compose file is also a deliverable in
  Приложение В (instruction for administrator).
- **Rejected: Kubernetes / minikube.** Adds a layer the grader does not need.

### Optional AWS leg

- **Terraform module + boto3 adapter, off by default.**
- **Why:** demonstrates portability without making the local path depend on
  a cloud account.

### Logging pipeline

- **Vector (toml-configured) reading nginx access log → ClickHouse HTTP sink.**
- **Why:** Vector handles back-pressure, parses JSON access logs, and ships
  natively to ClickHouse. One container, no JVM.
- **Rejected: Filebeat + Logstash.** Two extra processes, JVM footprint.

## Consequences

- The defended stack is reproducible on a single laptop with a one-line `make
  up` command, and the optional AWS leg does not gate any other deliverable.
- Two storage engines double the operational surface; mitigated by the fact
  that the grader sees only Compose, not raw psql/clickhouse-client.
- ML stays a separate service (next ADR will cover its boundaries).

## Follow-ups

- ADR-0002 — Online-vs-offline boundary for the ML service.
- ADR-0003 — Log schema and retention policy in ClickHouse.
- ADR-0004 — RBAC model for the panel.

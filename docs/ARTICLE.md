# Building a hybrid WAF, end-to-end

> A 14-week deep-dive into combining a rules engine (ModSecurity + OWASP CRS)
> with an ML anomaly detector behind a single management panel. What I picked,
> what I changed my mind about, and what I'd do differently.

I built **waf-panel** as a course project at IEML, but I deliberately scoped it
to look more like a small open-source product than a typical homework
submission. The goal: walk through every layer of a real defensive system —
from the edge where bytes arrive at nginx, through ModSecurity's regex engine,
through an ML scorer that runs in a budget of 5 ms, all the way up to the
React panel an operator stares at — without taking shortcuts that wouldn't
survive a pull-request review.

This article is the post-mortem. The repository is the artefact; this is how
I got there and what I'd change.

---

## The problem statement, before any code

Web application firewalls have two failure modes:

1. **They block real traffic.** Every operator has stories about a CRS rule
   that fired on a legitimate POST and burned an afternoon. The cost is paid
   in ops time and customer churn.
2. **They miss attacks the rules don't know about.** Zero-days, novel SQLi
   payload encodings, slow-burn credential stuffing — these slide right through
   a static ruleset.

Pure rules-based systems lean toward (1). Pure ML-based systems lean toward
(2). The interesting question is whether you can compose them so the rules
catch what they're good at (the long tail of known patterns) and the ML
catches what they're not (anomalous traffic shape), without making the
operator's life worse.

That's the thesis I tried to test.

## Architecture in one paragraph

A request arrives at nginx; ModSecurity v3 evaluates it against OWASP CRS v4
(1700 rules, paranoia level 1). If CRS denies, the request is gone — synchronous
block, no ML involved. If CRS lets it through, an `access_by_lua` hook fires a
subrequest to a separate `ml-service` container with a 5 ms budget; the service
scores the request through XGBoost + Isolation Forest and either annotates the
response (anomaly observed but allowed) or contributes to a block decision when
threshold-mode is on. Vector tails both nginx access logs and ModSec audit logs
into ClickHouse for analytics. A FastAPI gateway serves a React panel that
exposes the rule editor, incident feed, audit log, drift reports, and ML
threshold slider. PostgreSQL holds rules / users / audit / ML model metadata;
ClickHouse holds the high-volume traffic events. Redis carries the login
rate-limit and the ML inference cache. The whole thing comes up with
`docker compose up -d`.

That's the elevator pitch. Now the trade-offs.

---

## Trade-off #1: Why ModSecurity *and* ML, not one or the other

The recruiter-friendly answer is "defence in depth". The honest answer is that
the two systems have orthogonal failure modes:

- ModSecurity has near-zero recall on novel attacks but extremely well-understood
  precision: if rule 942100 fires, an analyst can pull the rule out of the CRS
  source tree and explain what it matched. Auditability is built in.
- An anomaly model can flag unfamiliar traffic shape (a UA string pattern
  never seen in training, a path-depth distribution that doesn't match the
  baseline), but its precision varies with the threshold and its
  explainability is fragile. Tell a customer "we blocked you because the
  XGBoost score was 0.83" and they'll ask why 0.82 was fine.

Composing them lets each cover the other's blind spot. The synchronous block
layer is still ModSec, so the ML can fail open without taking customers down;
the ML layer adds soft signals (a header, a flag in ClickHouse) that drive
analyst review without bypassing the auditable rules path.

The thing I'd push back on: this composition only works because the ML is
opt-in to the block decision. The default is annotate-only. If you flipped
that — block by default, with the rules as a fallback — you'd inherit all the
ML's precision pain and lose ModSec's "every block has a rule id"
auditability.

## Trade-off #2: ClickHouse for traffic, Postgres for state

I went into this thinking I might run everything on Postgres with a
`traffic_events` table. The numbers killed that idea fast: at modest test
load (200 RPS sustained, 50 KB average payload) Postgres was eating 30 MB/s
of WAL, and the dashboard's "RPS over the last hour" query was running 800 ms.

Switching the high-volume path to ClickHouse meant:

- Vector tails the nginx JSON access log and the ModSec audit log, parses both,
  and writes into `traffic_log` and `modsec_log` tables.
- Materialized views (`rps_per_minute`, `top_attacks_lifetime`) pre-aggregate
  the slices the dashboard actually reads. The "RPS over the last hour" query
  is now a single scan over the per-minute view.
- Postgres keeps the OLTP-shaped state: rules, users, the ML model registry,
  the audit log. These tables are small (rules max out at low thousands; the
  audit log is bounded by retention policy) and benefit from Postgres' row-level
  locking and Alembic-shaped migration story.

The cost is two databases to maintain. The benefit is each one is doing what
it's good at, and dashboard reads stay sub-100 ms even on the noisier traffic
runs in `bench/`.

## Trade-off #3: A separate ml-service container

The naive design was to load joblib models inside the FastAPI gateway and
call them in the request handler. That works at one RPS; at 200 RPS the
30 ms p99 of XGBoost prediction stalls every other backend request because
joblib's models are not async-friendly and would tie up the worker pool.

Solution: `ml-service` is its own FastAPI process with its own joblib state,
its own Redis cache, its own /healthz endpoint. The backend proxies
`POST /api/v1/ml/inspect` to it with a 20 ms p99 timeout and a fail-open
contract: if ml-service is down, slow, or returns a 5xx, the panel ignores it
and serves the operator the rules-only verdict with a `fallback: true` flag in
the JSON envelope. The frontend renders the flag as a "ML unavailable" pill so
operators know their picture is incomplete.

This pattern paid for itself the first time I shipped a model with a
serialisation bug — ml-service crashed on every request, but the panel kept
working because the proxy fail-open absorbed it. Production decoupling for
free.

## Trade-off #4: Cookie auth + CSRF, not Bearer in localStorage

Every SPA tutorial on the internet shows you how to put a JWT in
`localStorage` and call it "auth". I did this in the first version too. Then
the security audit pointed out that the panel's job is to ingest
attacker-controlled traffic and render it: any future XSS in a rule editor
preview gives an attacker the operator's session.

ADR-0014 documents the migration. The summary: the JWT now lives in an
httpOnly cookie that JS cannot read (`waf_session`). A second cookie
(`waf_csrf`) carries a 32-byte random token; it's intentionally not httpOnly
because the SPA needs to read it. On every mutating request the SPA echoes
the same value in `X-CSRF-Token`; a Starlette middleware compares cookie
against header and 403s on mismatch. CLI users keep the Bearer header path
(`Authorization: Bearer <jwt>`) so smoke scripts and curl examples in the
README don't need to learn cookie jars; the middleware exempts Bearer-auth'd
calls because they have no implicit credential to abuse.

Lesson learned: cookie-based auth is more code than localStorage but it puts
the JWT outside the JS context. That's worth it for any panel that
deliberately renders untrusted content.

## Trade-off #5: PSI + KS for drift, not "is the F1 score still good?"

A common drift-detection strategy is to keep a held-out validation set and
score the deployed model against it weekly. That works for systems where
ground truth is fast — fraud detection, medical screening — but for a WAF
your "labels" are an analyst going back through a week of incidents and
saying which were really attacks. Ground truth lags by weeks.

Drift detection that doesn't need fresh labels: distribution shift on the
input features. PSI (Population Stability Index) and KS (Kolmogorov-Smirnov)
both compare the current feature distribution against a frozen baseline
captured at training time; both flag the kind of shift that breaks an
ML model — the request mix changes, the path-depth distribution skews,
attackers start sending UTF-8 path components — without needing any
post-hoc labelling.

The drift worker (`backend/src/waf_panel/workers/drift_worker.py`) runs
on a schedule, pulls the last 24 hours from `traffic_log`, runs them through
the same `featurize()` function the trainer used, and computes PSI + KS
against the baseline. Verdicts land in `audit_log` with action
`ml.drift.{alert,warn,clean}` and a JSON report under `ml/drift_reports/`.
The panel surfaces the reports on a Drift page so an analyst doesn't have to
SSH in to read them.

What I'd change: the baseline is currently captured at train time and never
updated. A real production system would periodically re-baseline against a
"clean enough" sliding window so seasonal shifts don't generate alerts.
That's tracked as a follow-up.

---

## Things I changed my mind about

**I started thinking the panel should ship with a built-in dashboard editor.**
After the first prototype I realised I was reinventing Grafana badly. The panel
now sticks to the operational moves an analyst takes (review incidents, edit
rules, rotate threshold, see drift) and exposes a Prometheus `/metrics`
endpoint for everything else. If you want a custom dashboard, you wire it in
Grafana like any other service. Less code, more leverage.

**I started thinking the rule editor should validate ModSec syntax in the
browser.** The CRS grammar is ugly and full of edge cases; reimplementing the
parser in TypeScript is exactly the kind of project that's cool for a week and
unmaintained for a year. Now the editor saves the raw text, and ModSec's own
loader rejects invalid rules at next reload. The error path is "the next
deploy fails clearly" — not as nice as inline validation, but the failure
mode is loud and the implementation is tiny.

**I started believing fail-closed was the secure default.** It almost always
is, but for a WAF specifically — where the alternative to "fail closed" is
"deny all customer traffic when ml-service blips" — the answer is fail-open,
plus loud telemetry, plus a soft block-mode that operators turn on only after
calibration. The audit trail catches the cases where fail-open was wrong; the
SLA stays intact.

## What I'd do differently next time

- **Pin dependencies more aggressively.** I went with `>=` ranges in the
  pyproject files, and pip-audit caught a transitive vuln on a sub-dependency
  that wouldn't have shipped if I'd pinned. Worth the noise.
- **Use OpenTelemetry from day one.** I added Prometheus + structured logging
  late (#129); the next time I'm reaching for `print()` I should reach for
  `tracer.start_as_current_span()` instead. The cost is a single import; the
  benefit is full request traces from nginx through ml-service.
- **Treat the threat model as a living document.** I wrote `docs/threat-model.md`
  in week 12 as a kind of project deliverable. It would have been more useful
  in week 2, gating every architectural choice ("does this make any of the
  STRIDE rows worse?"). I'd start with it next time, not finish with it.
- **Skip i18n on the first pass.** It's now in four languages, which is a
  lovely demo, but every new feature pays an i18n tax and the project's
  intended audience is English-reading operators. Localising late once the
  feature set is stable would have saved a couple of weeks.

## What I'd defend at code review

- The two-database split (Postgres for state, ClickHouse for traffic) is
  the right call even at this scale. The dashboard latency budget alone
  justifies it.
- Cookie + CSRF over Bearer in localStorage. The threat model demands it
  for any panel that renders attacker-controlled content.
- ml-service as a separate container with a fail-open backend proxy. The
  first time it crashes you get the value back.
- The 25-feature `featurize()` contract being shared between the trainer,
  the drift worker, and the inference path through a single Python module.
  The drift detector uses the *same* featurization the model was trained on;
  you cannot get a column mismatch unless you change the source code in three
  places at once, which is exactly the level of difficulty I want for that
  invariant.
- Refusing to start under `WAF_ENV=production` with the default JWT secret or
  the default admin password. Zero false-positive cost; a real production
  footgun closed.

## What this taught me

If you go into a project like this thinking "I'm building a WAF" you'll
build a worse one than if you go in thinking "I'm building a system that has
to be debuggable, deployable, and explicit about its failure modes". The
WAF-specific decisions (which rules, which features, which threshold) are
the easy part — they're documented choices with well-understood trade-offs.
The hard part is the production scaffolding: cookies vs Bearer, fail-open vs
fail-closed, two databases or one, where the seams are between async log
shipping and synchronous block decisions. Those choices compound.

The repo at <https://github.com/Terraxell/waf-panel> is the working artefact.
The CHANGELOG tells the story chronologically; this article tells it
thematically. Read whichever fits how your brain is wired.

---

*— Gennadii Panteleev, 2026*
*Course project at IEML, "Internet Programming" discipline (variant #14, extended).*
*Reach me: Terraxell@gmail.com*

# Security policy

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | ✅                 |
| < 1.0   | ❌                 |

This is a course / portfolio project, not a managed service. The
versions list reflects which release line still receives security
fixes if a vulnerability is reported.

## Reporting a vulnerability

Please **do not** open public issues for security problems. Instead:

1. Email **Terraxell@gmail.com** with the subject prefix `[security]`.
2. Include:
   - A clear description of the vulnerability.
   - Steps to reproduce (or a proof-of-concept request).
   - The version / commit hash you tested against.
   - Your assessment of severity (CVSS-like scoring is appreciated
     but optional).

I will acknowledge receipt within **72 hours** and aim to confirm
the issue (or explain why it is not one) within **7 days**.

## What this project takes seriously

The threat model lives in [`docs/threat-model.md`](docs/threat-model.md).
Beyond that, these classes are explicit-priority:

- **Authentication bypass.** Any path that hands a non-admin user
  admin role, or a non-authenticated request a session cookie.
- **Stored XSS / template injection** in the rule editor or audit
  payload viewer (the panel ingests attacker-controlled traffic by
  design, so any unsanitised render is high-impact).
- **CSRF** — the whole point of ADR-0014; cookie auth without the
  X-CSRF-Token header should always be rejected for mutating verbs.
- **Default-credential foothold.** The startup guard in
  `_validate_admin_password_in_production` plus the JWT_SECRET guard
  block the two known footguns; anything similar should be flagged.

## What this project explicitly does not promise

- Confidentiality of self-hosted Postgres / ClickHouse data — that's
  on the operator. The runbook covers backup but not encryption-at-
  rest configuration.
- Resilience of `ml-service` against adversarial inputs designed to
  flip the threshold. Anomaly detection is best-effort; ModSecurity
  is the synchronous block layer.

## Disclosure timeline

Once a confirmed vulnerability is fixed:

1. The fix lands as a regular PR, with a redacted commit message
   (the full impact note is held until step 3).
2. A new patch release is tagged (`v1.0.X+1`).
3. After the release, a `SECURITY-ADVISORY-yyyy-mm-dd.md` is added
   to `docs/` describing the issue, fix, and credit (with the
   reporter's permission). GitHub Security Advisory is also filed
   so the GHSA database picks it up.

Reporters who want public credit get it. Reporters who don't, don't.

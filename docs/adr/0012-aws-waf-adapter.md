# ADR-0012 — AWS WAF adapter: optional, IPSet-only, fail-soft

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The methodology lists "AWS WAF integration" as part of the variant-14
extended scope. We don't want it on the hot path — the gateway already
makes block decisions locally. What's actually useful is *propagating*
local-decision blocklists out to AWS WAF so cloud-fronted assets
(CloudFront, ALB) stop the same attackers before they reach our nginx.

## Decision

### One direction only: panel → AWS

The adapter is unidirectional. The panel is the source of truth;
AWS is a downstream replica. Concretely:

- `sync_ip_blocklist()` reads the top-N attacker IPs from
  `traffic_log` (last 24 h, `event_type IN ('modsec', 'ml_block')`,
  grouped by `remote_ip`, filtered by `count() > N`) and pushes the
  list into a configured `IPSet` via `boto3.client("wafv2").update_ip_set`.
- We never *read* AWS counters back. If ops want to compare, they
  use AWS CloudWatch directly.

WHY one-way: bidirectional sync needs version vectors and conflict
resolution; out of scope for a course project.

### Behind two feature flags

```
WAF_AWS_ENABLED=true       # the adapter is loaded
WAF_AWS_REGION=us-east-1
WAF_AWS_IPSET_ID=...
WAF_AWS_IPSET_NAME=...
WAF_AWS_SCOPE=REGIONAL     # or CLOUDFRONT
```

Default `WAF_AWS_ENABLED=false`. The backend imports the adapter
*lazily* — `boto3` itself is only required when the flag is on.

### Fail-soft on AWS errors

AWS API can throttle, return a stale lock token, or reject because
the IPSet hit its 10000-address limit. Each failure mode:

1. Logged to `audit_log` with `action="aws_waf.sync_failed"` and the
   AWS error code in the payload.
2. Swallowed — never propagates to the user-facing API.
3. Reported via `GET /api/v1/integrations/aws_waf/status` so the
   operator can decide.

The on-prem ModSec + ML block stack continues to work regardless.

### Rate limiting

AWS `UpdateIPSet` is 1 RPS per API key. We enforce 5-minute
quarantine in code (a Redis key with TTL) so pressing «Sync» twice
in a minute is a no-op.

## Consequences

Positive:
- Cloud-edge protection without complicating the on-prem path.
- Fail-soft means AWS being down is a non-event for the gateway.
- Single boundary: one method, one code path, one audit signature.

Negative:
- Operators must remember that the panel is the source of truth.
- AWS-side manual rules are not reflected back; documented.

## Alternatives considered

- **AWS WAF as the *primary* block layer.** Rejected — defeats the
  ML latency advantage of local blocking.
- **WAF Bot Control / Captcha integration.** Out of scope; would need
  a JS challenge flow on the panel side.
- **Use AWS Network Firewall (NFW) instead.** NFW is L3/L4-oriented;
  HTTP-feature-aware filtering is what AWS WAF is for. NFW is a
  future release option for IP rate-limiting at the VPC edge.

## Follow-ups

-  — scheduled sync (cron in the backend).
- ADR-0014 — multi-region IPSet fan-out.

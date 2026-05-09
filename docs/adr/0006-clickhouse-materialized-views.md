# ADR-0006 — ClickHouse materialized views for hot dashboard queries

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The dashboard polls `/metrics/timeseries` every 30 seconds per active
session. The endpoint scans `traffic_log` from `now() - INTERVAL 1 HOUR`
for each call. At project scale this is fine (<10 ms), but after a few
attack-bench runs the table gets to ~100k–1M rows, and the same scan
becomes ~100 ms — most of the dashboard's perceived latency.

ClickHouse materialized views (MV) are the canonical tool for this:
the view pre-aggregates rows on INSERT and stores the result in its
own `MergeTree` table. Reads against the MV are constant-time over the
**bucket count**, not over the input row count.

## Decision

Two MVs, both in `waf_logs`:

### `mv_rps_per_minute`

Bucketed counts of access vs. modsec events per minute. Powers the
`/metrics/timeseries?bucket=minute` endpoint.

```sql
CREATE TABLE waf_logs.rps_per_minute (
    minute   DateTime('UTC'),
    total    UInt64,
    blocked  UInt64
) ENGINE = SummingMergeTree
PARTITION BY toYYYYMMDD(minute)
ORDER BY (minute);

CREATE MATERIALIZED VIEW waf_logs.mv_rps_per_minute
TO waf_logs.rps_per_minute AS
SELECT
    toStartOfMinute(ts) AS minute,
    count()             AS total,
    countIf(event_type = 'modsec') AS blocked
FROM waf_logs.traffic_log
GROUP BY minute;
```

### `mv_top_attacks_24h`

Sorted paths by modsec-event count, only over the trailing 24h window.
Powers the "TOP-АТАКИ ЗА 24Ч" card.

```sql
CREATE TABLE waf_logs.top_attacks_24h (
    path  String,
    hits  UInt64
) ENGINE = SummingMergeTree
ORDER BY (path);

CREATE MATERIALIZED VIEW waf_logs.mv_top_attacks_24h
TO waf_logs.top_attacks_24h AS
SELECT path, count() AS hits
FROM waf_logs.traffic_log
WHERE event_type = 'modsec' AND ts > now() - INTERVAL 24 HOUR
GROUP BY path;
```

## Why now  and not earlier

Until  the dashboard didn't read ClickHouse at all. We needed
the actual query shapes locked-in before promoting them to MV — moving
an MV is more expensive than rewriting an endpoint.

## Alternatives considered

- **Keep raw scans.** Simple, but ages poorly. Once the supervisor
  replays a one-hour attack-bench, the dashboard chokes.
- **External cache (Redis) on the API layer.** Introduces inval
  semantics and a TTL knob; ClickHouse already owns the freshness
  question via the MV's INSERT-time aggregation. No reason to add a
  second cache.
- **AggregatingMergeTree with state functions.** Cleaner for nested
  aggregates, but needs `*-State` functions and merging at read-time.
  `SummingMergeTree` is enough for plain `count()` cases and is
  obviously correct.

## Consequences

- `init.sql` grows by ~30 lines; safe re-apply because everything is
  `IF NOT EXISTS`.
- Endpoints don't change shape. They start to issue the cheaper query
  against the MV target table; the API contract is unchanged.
- A new operational consideration: if `traffic_log` is truncated (dev
  reset), the MVs go out of sync. Ships: a `make ch-reset`
  helper that drops + recreates the MVs in one step.

## Follow-ups

- Once we have ML scores per request , add an MV
  `mv_score_distribution_hourly` for the drift dashboard.

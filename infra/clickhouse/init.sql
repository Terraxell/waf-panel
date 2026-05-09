-- waf-panel — ClickHouse bootstrap.
-- WHY: docker-entrypoint runs *.sql once on first boot. Anything that
--      changes later belongs in a numbered migration, but Sprint 6's
--      schema is small enough to keep here as IF NOT EXISTS.

CREATE DATABASE IF NOT EXISTS waf_logs;

-- ── raw traffic ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS waf_logs.traffic_log (
    ts          DateTime64(3, 'UTC') CODEC(Delta, ZSTD(3)),
    event_type  LowCardinality(String),
    remote_ip   String,
    method      LowCardinality(String),
    path        String CODEC(ZSTD(3)),
    query       String CODEC(ZSTD(3)),
    status      UInt16,
    bytes       UInt32,
    latency_ms  Float32,
    ua          String CODEC(ZSTD(3)),
    referer     String CODEC(ZSTD(3)),
    rule_ids    Array(String) CODEC(ZSTD(3)),
    raw         String CODEC(ZSTD(6))
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (ts, remote_ip, path)
TTL toDateTime(ts) + INTERVAL 30 DAY;

-- ── ML features ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS waf_logs.traffic_features (
    ts          DateTime64(3, 'UTC'),
    request_id  String,
    method      LowCardinality(String),
    len_url     UInt32,
    len_query   UInt32,
    len_body    UInt32,
    n_params    UInt16,
    n_special   UInt16,
    entropy_path Float32,
    is_bot      UInt8,
    label       Int8
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (ts, request_id);

-- ── Materialized views (Sprint 6) ───────────────────────────────────
-- WHY: dashboard polls every 30 s; pre-aggregating on INSERT keeps reads
--      fast as the log volume grows. See ADR-0006.

-- Per-minute RPS + blocked counters, filling SummingMergeTree.
CREATE TABLE IF NOT EXISTS waf_logs.rps_per_minute (
    minute   DateTime('UTC'),
    total    UInt64,
    blocked  UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMMDD(minute)
ORDER BY (minute);

CREATE MATERIALIZED VIEW IF NOT EXISTS waf_logs.mv_rps_per_minute
TO waf_logs.rps_per_minute AS
SELECT
    toStartOfMinute(ts) AS minute,
    count()             AS total,
    countIf(event_type = 'modsec') AS blocked
FROM waf_logs.traffic_log
GROUP BY minute;

-- Per-path attack counts, refreshed continuously. Read with a 24h filter
-- on the application side; the MV holds full history but the query is
-- still cheap because we sum at read-time.
CREATE TABLE IF NOT EXISTS waf_logs.top_attacks_lifetime (
    bucket_day Date,
    path       String,
    hits       UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(bucket_day)
ORDER BY (path, bucket_day);

CREATE MATERIALIZED VIEW IF NOT EXISTS waf_logs.mv_top_attacks
TO waf_logs.top_attacks_lifetime AS
SELECT
    toDate(ts)  AS bucket_day,
    path        AS path,
    count()     AS hits
FROM waf_logs.traffic_log
WHERE event_type = 'modsec'
GROUP BY bucket_day, path;

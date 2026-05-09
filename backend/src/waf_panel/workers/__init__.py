"""Out-of-band workers — scheduled jobs that aren't on the request path.

Currently: drift_worker ( — runs `waf_ml.drift` against a frozen
baseline + a recent ClickHouse window, writes an audit row when alert).
"""

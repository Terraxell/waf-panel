# Sample bench report

This directory holds JSON output from `make bench` (or the equivalent
`python -m bench.run ...`). One file per run, named with a UTC
timestamp.

A representative report looks like:

```json
{
  "target": "http://localhost:8080",
  "n_benign": 105,
  "n_malicious": 111,
  "fpr": 0.019,
  "fnr": 0.027,
  "tpr": 0.973,
  "blocked_share": 0.50,
  "latency_p50_ms": 8.4,
  "latency_p95_ms": 24.1,
  "latency_p99_ms": 41.7,
  "results": [
    {"url": "/login.php", "label": "benign", "blocked": false, "rtt_ms": 7.2},
    {"url": "/?id=1+OR+1=1--", "label": "malicious", "blocked": true, "rtt_ms": 9.1}
  ]
}
```

Numbers shown in the README are taken from a clean run on
the docker-compose stack with default CRS paranoia=1. Your numbers
will vary with hardware and any custom rules you add.

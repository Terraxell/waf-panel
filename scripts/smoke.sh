#!/usr/bin/env bash
# scripts/smoke.sh — verify the local stack actually defends.
# WHY: a single command that proves: proxy is up, DVWA is reachable through
#      it, ModSecurity blocks a known SQLi payload, traffic is logged.

set -euo pipefail

PROXY="${PROXY_URL:-http://localhost:8080}"
CH_HOST="${CH_HOST:-http://localhost:8123}"
CH_USER="${CH_USER:-waf}"
CH_PASS="${CH_PASSWORD:-waf_dev_only}"
CH_DB="${CH_DB:-waf_logs}"

ok()   { echo "[ok]   $*"; }
fail() { echo "[fail] $*"; exit 1; }
hr()   { printf '%.0s-' {1..60}; echo; }

hr
echo "smoke: ${PROXY}"
hr

# 1. proxy responds at all
code=$(curl -s -o /dev/null -w "%{http_code}" "${PROXY}/__health" || true)
[[ "$code" == "200" ]] || fail "proxy /__health returned $code"
ok "proxy is up"

# 2. DVWA reachable through proxy (302 to /login.php is normal)
code=$(curl -s -o /dev/null -w "%{http_code}" "${PROXY}/" || true)
[[ "$code" =~ ^(200|302)$ ]] || fail "DVWA via proxy returned $code"
ok "DVWA reachable through proxy"

# 3. ModSecurity blocks an obvious SQLi payload
code=$(curl -s -o /dev/null -w "%{http_code}" "${PROXY}/?id=1%20OR%201%3D1--" || true)
[[ "$code" == "403" ]] || fail "expected 403 from ModSecurity, got $code"
ok "ModSecurity blocked a SQLi payload (HTTP 403)"

# 4. log shipper has written rows into ClickHouse
sleep 2
rows=$(curl -s -u "${CH_USER}:${CH_PASS}" "${CH_HOST}/?database=${CH_DB}" \
    --data-urlencode 'query=SELECT count() FROM traffic_log' || true)
case "$rows" in
    ''|*[!0-9]*) fail "could not query ClickHouse (got: '$rows')" ;;
    *)           ok "traffic_log rows: $rows" ;;
esac

hr
echo "smoke: PASSED"
hr

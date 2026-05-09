# ADR-0010 — OpenResty + Lua subrequest as opt-in proxy flavour

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

 placed `ml-service` next to the gateway. The dashboard
calls it via the backend proxy, but the request *itself* is not
yet scored synchronously on the nginx side.  wants
block-mode (`prob > 0.95 → 403`); to keep p99 under 20 ms we need
the subrequest to fire from nginx, not from a proxied backend
round-trip.

The complication: the upstream image
`owasp/modsecurity-crs:nginx-alpine` is built with mainline nginx
+ libmodsecurity, **without** `lua-nginx-module`. There is no
official combined image. Switching means a from-source build of
nginx with both modules — a real change.

## Decision

### Two proxy flavours, one selected at compose time

We keep the current image (`proxy/Dockerfile`) as the default and
add a parallel `proxy/Dockerfile.openresty` that builds OpenResty
with libmodsecurity + ModSecurity-nginx. The compose file uses

```yaml
proxy:
  build:
    context: ./proxy
    dockerfile: ${PROXY_FLAVOR_DOCKERFILE:-Dockerfile}
```

Operators set `PROXY_FLAVOR_DOCKERFILE=Dockerfile.openresty` in
`.env` to opt in. Default flow remains the CP-2 demo image.

### Lua-subrequest at access phase, fail-open

```lua
-- score.lua, called from access_by_lua_block
local res = ngx.location.capture("/__ml_score", {
    method = ngx.HTTP_POST,
    body   = body_table_to_json(),
})
if not res or res.status >= 500 or not res.body then
    return  -- fail open: ML down → ModSec keeps deciding
end
local ok, body = pcall(cjson.decode, res.body)
if not ok or not body.prob then return end
if body.prob >= tonumber(ngx.var.ml_block_threshold) then
    --  enables this block;  only annotates.
    -- ngx.exit(403)
end
ngx.req.set_header("X-WAF-ML-Prob", tostring(body.prob))
```

Two SLOs, both enforced in the Lua side:
- ngx_lua's own `proxy_read_timeout = 5ms` for the subrequest.
- Any non-2xx, missing body, or decode failure → fail open. The
  rule is identical to backend-proxy: ML must never break the
  request path.

### What this ADR explicitly defers

- **Block-mode toggle.** Ships: the Lua wiring in *annotate*
  mode (header only).  flips the threshold check on after
  CSIC/CICIDS calibration.
- **In-Lua feature extraction.** No. Lua sends the raw fields
  (method/path/query/UA) and `ml-service` calls `featurize`. One
  source of truth; LuaJIT replicating Python feature math is the
  way to silent quality regressions.
- **Per-route opt-out.**  — `location ~* ^/static/` would
  skip the subrequest to save latency on cacheable assets.

## Consequences

Positive:
- Default demo path stays exactly as it was for CP-2.
- A clean, deliberate switch when we want block-mode.
- ML latency budget for online block-mode: 5 ms p95 + 1 ms LuaJIT
  overhead, well within nginx's tail.

Negative:
- Two Dockerfiles to keep in sync (config drift risk).
- OpenResty image build is ~20 minutes vs 30 seconds for the
  upstream CRS image. Documented in `docs/troubleshooting.md`.
- `lua-resty-redis` would let Lua hit Redis directly and skip
  `ml-service` on cache hits  optimisation.

## Alternatives considered

- **Stay in-process via njs (nginx JavaScript module).** Available
  in mainline nginx, no Lua needed. Rejected: njs HTTP subrequests
  are flaky on Alpine + libmodsecurity combinations and the
  community examples are sparse.
- **Sidecar `auth_request` directive.** Works without Lua but is
  HEAD-only; can't pass body to the score endpoint.
- **APISix / Kong as the proxy.** Way too much for a course
  project; would re-do all of the initial release.

## Follow-ups

- ADR-0011 — block-mode threshold + rollback procedure.
-  — calibration + threshold flip.
-  — `lua-resty-redis` for cache short-circuit.

## Addendum  — per-route opt-out

Static assets, favicon, health/ready endpoints don't benefit from ML
scoring and shouldn't pay the 5 ms budget. The OpenResty template now
defines explicit `location` blocks for `^/static/`, `/favicon.ico`,
`/robots.txt`, `/__health`, `/healthz`, `/readyz` that **omit**
`access_by_lua_file`. Three reasons:

1. **Latency.** Cacheable assets are served without an extra round-trip
   to ml-service.
2. **Capacity.** ml-service doesn't waste decisions on `*.css` / `*.png`.
3. **Health-probe safety.** A sick ml-service must NEVER cause its own
   healthcheck to fail; running Lua on `/healthz` would create that
   exact loop.

ModSecurity still runs on the asset paths (CRS rules apply). Health
endpoints disable ModSec explicitly because they have zero user input
and the rule overhead would only ever produce false positives.

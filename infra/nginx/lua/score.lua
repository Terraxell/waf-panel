-- score.lua — fail-open ML subrequest from access_by_lua.
--
-- WHY: in this release we *annotate* (header X-WAF-ML-Prob);  will flip
-- the block on. Either way, the contract is:
--   1. ML subrequest budget = 5 ms. Anything slower → fail open.
--   2. Any non-2xx, missing body, or decode failure → fail open.
--   3. ML must NEVER cause a 5xx out of the gateway.
--
-- The body sent to /__ml_score mirrors the ml-service ScoreRequest schema.

local cjson = require "cjson.safe"

local function safe_get(name)
    local v = ngx.var[name]
    if v == nil then return "" end
    return v
end

local function fail_open(reason)
    -- WHY: we do *not* deny the request. We just leave the ModSec verdict
    -- in charge. The header is for Vector → ClickHouse so analysts can see
    -- which requests fell through ML.
    ngx.req.set_header("X-WAF-ML-Fallback", reason)
end

-- Build the JSON body for ml-service.
local payload = cjson.encode({
    method = ngx.req.get_method() or "GET",
    path = safe_get("uri") or "/",
    query = safe_get("args") or "",
    body = "",  -- WHY: reading the request body from access_by_lua is
                --      possible (ngx.req.read_body) but adds latency we
                --      don't have in the 5 ms budget. ml-service can decide
                --      based on path/query/UA alone in the common case;
                --       will revisit if recall suffers.
    user_agent = safe_get("http_user_agent"),
    referer = safe_get("http_referer"),
})

-- ngx.location.capture honours the location's proxy_read_timeout; see
-- the matching `internal` block in default.conf.template.
local res = ngx.location.capture("/__ml_score", {
    method = ngx.HTTP_POST,
    body = payload,
})

if not res or res.status >= 500 or not res.body then
    return fail_open("ml_unreachable")
end
if res.status >= 400 then
    return fail_open("ml_bad_request")
end

local ok, body = pcall(cjson.decode, res.body)
if not ok or type(body) ~= "table" or body.prob == nil or body.prob == cjson.null then
    return fail_open("ml_bad_payload")
end

-- this release: opt-in block-mode behind ml_block_threshold.
-- Default 1.0 → never blocks. Operator lowers it after calibration.
local threshold = tonumber(ngx.var.ml_block_threshold) or 1.0
local prob = tonumber(body.prob) or 0.0

ngx.req.set_header("X-WAF-ML-Prob", tostring(prob))
ngx.req.set_header("X-WAF-ML-Model", tostring(body.model or ""))
ngx.req.set_header("X-WAF-ML-Version", tostring(body.model_version or ""))
ngx.req.set_header("X-WAF-ML-Threshold", tostring(threshold))

if threshold < 1.0 and prob >= threshold then
    -- WHY: emit the reason header BEFORE exit so Vector logs see it
    --      (ngx.exit cuts the request short, but headers already in
    --      response state).
    ngx.header["X-WAF-ML-Reason"] = "ml-block"
    ngx.header["X-WAF-ML-Prob"] = tostring(prob)
    return ngx.exit(ngx.HTTP_FORBIDDEN)
end

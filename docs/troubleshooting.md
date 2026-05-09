# Troubleshooting

A short log of issues we hit on the local stack and how to resolve them.
Each entry: what you see → why → fix. Eleven entries, roughly in the
order we ran into them while bringing up Sprint 4.

## proxy keeps restarting with `Invalid input: block`

### Symptom

```
waf-proxy  | [emerg] 1#1: "modsecurity_rules_file" directive Rules error.
waf-proxy  | File: /etc/modsecurity.d/modsecurity.conf. Line: 5. Column: 20.
waf-proxy  | Invalid input: block
```

### Why

ModSecurity's `SecRuleEngine` directive only accepts three literal values:
`On`, `Off`, or `DetectionOnly`. The original `.env.example` shipped with
`MODSEC_RULE_ENGINE=block`, which `envsubst` substituted into the config
template. ModSecurity refused to parse it and nginx exited with `[emerg]`.

### Fix

```powershell
(Get-Content .env) -replace 'MODSEC_RULE_ENGINE=.*', 'MODSEC_RULE_ENGINE=On' |
    Set-Content .env
docker compose up -d --force-recreate proxy
```

The repository's `.env.example` is corrected and the compose default is
also `On`.

## Frontend image fails on `npm install`

### Symptom

```
> [frontend builder 4/6] RUN npm install ...
target frontend: failed to solve: process did not complete successfully: exit code: 1
```

### Why

Lockfile generated on Windows pins platform-specific Rollup binaries that
don't exist on Linux. npm 10 has a known bug (npm/cli#4828) where it
won't fall back to the matching linux native when the lockfile is
present.

### Fix

Already in the repo: `frontend/.dockerignore` excludes the lockfile and
`frontend/Dockerfile` runs `npm install --include=optional` so the linux
binaries resolve fresh inside the container.

```powershell
docker compose build --no-cache frontend
docker compose up -d
```

## Backend container is `unhealthy` with `ModuleNotFoundError: No module named 'uvicorn'`

### Symptom

```
waf-backend  | File "/install/bin/uvicorn", line 3, in <module>
waf-backend  | ModuleNotFoundError: No module named 'uvicorn'
```

### Why

Original `backend/Dockerfile` used `pip install --prefix=/install`. That
puts packages under `/install/lib/python3.11/site-packages/`, which is
not on `sys.path`. The `uvicorn` script ran but couldn't import its own
package.

### Fix

The Dockerfile now uses a venv at `/opt/venv` (canonical multi-stage
pattern). Force a fresh image:

```powershell
docker compose build --no-cache backend
docker compose up -d
```

## `relation "users" already exists` from `alembic upgrade head`

### Symptom

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.DuplicateTable)
relation "users" already exists
```

### Why

The Postgres volume is bootstrapped by `infra/postgres/init.sql` which
runs once on first volume creation. After that, `alembic upgrade head`
sees a database that already matches revision `0001` and tries to
re-create the same tables.

### Fix

For a volume already initialised by `init.sql` mark the database as
already migrated, do not re-run the SQL:

```powershell
docker compose exec backend alembic stamp head
```

For a fresh volume the migration is now idempotent — every
`op.create_table` is gated on `_table_missing()`, so `alembic upgrade
head` is a no-op when the tables already exist.

## Default panel login (`admin / admin`) returns 401

### Symptom

The login form rejects `admin@example.com` / `admin` with "Неверная
пара логин/пароль".

### Why

The first version of `infra/postgres/init.sql` seeded the admin user
with a placeholder argon2 hash. `verify_password("admin", placeholder)`
always returned False.

### Fix

The repository's `init.sql` now contains a real argon2id hash for
"admin". For an existing volume that already has the placeholder, run
the UPDATE once:

```powershell
$sql = 'UPDATE users SET password_hash = ''$argon2id$v=19$m=65536,t=3,p=4$xth7r9U6hxBCyLnX2vsfAw$IE88s0FMViFmVNpDk0B4Cv4U0fk8NHrh7g9UvPfdxWE'' WHERE email = ''admin@example.com'';'
docker compose exec postgres psql -U waf -d waf_panel -c $sql
```

## proxy restarts with `log_format directive is not allowed here`

### Symptom

```
[emerg] 1#1: "log_format" directive is not allowed here in
/etc/nginx/conf.d/default.conf:NN
```

### Why

`log_format` is valid only in `http {}` context. We initially placed it
inside `server {}`. The image includes our file via `conf.d/*.conf` —
already in `http`-context — so http-level directives go ABOVE the
`server` block, not inside it.

### Fix

Move `log_format` and any other http-only directives (`map`, `upstream`,
`geo`) to the top of `default.conf.template`, before `server { ... }`.
Done in the repo.

## `invalid parameter "$$time_iso8601"` after envsubst

### Symptom

```
[emerg] 1#1: invalid parameter "$$time_iso8601" in
/etc/nginx/conf.d/default.conf:NN
```

### Why

`$$VAR` is the **compose-level** escape syntax. Inside an nginx template
file, `envsubst` does not understand `$$` — it leaves both `$` literal,
producing `$$variable` in the rendered config, which nginx then can't
parse.

### Fix

In nginx template files use plain `$variable`. envsubst leaves
nginx-native variables alone if they have no matching env var. Done in
the repo.

## `Read-only file system` while envsubst writes the rendered config

### Symptom

```
20-envsubst-on-templates.sh: line 53: can't create
/etc/nginx/conf.d/default.conf: Read-only file system
```

### Why

The image's entrypoint always renders `/etc/nginx/templates/conf.d/*.template`
into `/etc/nginx/conf.d/*.conf`. If we bind-mount a file directly to
`/etc/nginx/conf.d/default.conf:ro`, envsubst can't overwrite it →
fatal.

### Fix

Bind-mount the template, not the rendered file:

```yaml
volumes:
  - ./infra/nginx/templates/default.conf.template:/etc/nginx/templates/conf.d/default.conf.template:ro
```

Done in the repo.

## CRS rule id 200000 is duplicated

### Symptom

```
"modsecurity_rules_file" directive Rules error. Rule id: 200000 is duplicated
```

### Why

The image already enables ModSecurity at `http {}` context via its
own `/etc/nginx/conf.d/modsecurity.conf`. Re-declaring `modsecurity on;`
and `modsecurity_rules_file ...;` inside our `server { }` block loads
the same setup.conf a second time, and CRS' bootstrap `id:200000` rule
collides with itself.

### Fix

Remove `modsecurity on;` and `modsecurity_rules_file ...;` from the
vhost template. ModSecurity is enabled at the http level for every
server block in the same nginx instance. Done in the repo.

## nginx `Permission denied` on `/var/log/nginx/access.json`

### Symptom

```
[emerg] 1#1: open() "/var/log/nginx/access.json" failed (13: Permission denied)
```

### Why

The named volume `waf_logs` mounts over `/var/log/`, masking the
image's pre-chowned `/var/log/nginx/`. The fresh volume directory is
owned by root, but nginx workers run as the `nginx` user (uid 101).

### Fix

`docker-compose.yml` now overrides the proxy entrypoint with a small
init step:

```yaml
user: "0:0"
entrypoint:
  - sh
  - -c
  - |
    mkdir -p /var/log/nginx
    chown -R nginx:nginx /var/log /var/log/nginx
    exec /docker-entrypoint.sh nginx -g "daemon off;"
```

After dropping the broken volume once (`docker volume rm
waf-panel_waf_logs`) the proxy container starts cleanly on every later
boot. Image's `/docker-entrypoint.sh` later drops privileges to nginx
user via the standard `user nginx;` directive in nginx.conf.

## Vector silently runs the demo pipeline

### Symptom

`docker compose logs vector` shows synthetic records like
`{"appname":"BryanHorsey","hostname":"random.ren", ...}` instead of our
nginx/modsec events.

### Why

Vector image's default CMD is `vector` without arguments. If our config
doesn't load (path wrong, syntax error), Vector falls back to a built-in
demo pipeline.

### Fix

Force-load the config explicitly:

```yaml
vector:
  command: ["--config", "/etc/vector/vector.toml"]
```

Done in the repo. After this, Vector either loads our config or fails
loudly with a parse error.

## Vector: `to_timestamp!()` undefined in 0.40

### Symptom

```
error[E105]: call to undefined function
6 │ .ts = format_timestamp!(to_timestamp!(ts), format: "...")
  │                         ^^^^^^^^^^^^ undefined function
  │                                       did you mean "is_timestamp"?
```

### Why

In Vector 0.40 VRL, `to_timestamp!()` for strings was replaced by
`parse_timestamp!()` with an explicit format argument.

### Fix

```text
ts_parsed, err = parse_timestamp(ts_str, format: "%+")
if err != null { ts_parsed = now() }
.ts = format_timestamp!(ts_parsed, format: "%Y-%m-%d %H:%M:%S%.3f")
```

`%+` parses RFC3339 / ISO8601 with optional TZ. Done in the repo.

## ClickHouse rejects timestamps with `+TZ` suffix in JSONEachRow

### Symptom

```
Code: 27. DB::Exception: Cannot parse input: expected '"' before:
'+00:00",...': (while reading the value of key ts):
(CANNOT_PARSE_INPUT_ASSERTION_FAILED)
```

### Why

`DateTime64(3, 'UTC')` columns in JSONEachRow expect the format
`YYYY-MM-DD HH:MM:SS.fff` — no `+TZ` offset. nginx writes
`$time_iso8601` as `2026-05-08T13:55:22+00:00`, which CH refuses.

### Fix

Reformat in Vector via `format_timestamp!(...,
format: "%Y-%m-%d %H:%M:%S%.3f")`. The column already lives in UTC, so
dropping the offset is correct. Done in the repo.

## Vector: env-substitution fires inside comments

### Symptom

```
ERROR vector::cli: Configuration error.
error=Missing environment variable in config. name = "time_iso8601"
```

### Why

Vector applies `${VAR}` and `$VAR` env-substitution to the **entire**
config file before parsing it — including commented-out lines. A
comment like `# nginx $time_iso8601 = ...` is read as a reference to a
non-existent env var.

### Fix

Strip stray `$` from comments. Use `${VAR}` only where you actually
mean to interpolate (the sink credentials). Done in the repo.

## `service "backend" is not running` when running `make migrate`

### Symptom

```
docker compose exec backend alembic upgrade head
service "backend" is not running
```

### Why

`docker compose up` failed earlier (frontend or backend image issue),
which left `backend` in a state where the orchestration never started
it.

### Fix

Resolve the upstream failure first, then:

```powershell
docker compose up -d
docker compose ps              # wait for "healthy"
docker compose exec backend alembic upgrade head
```

## `welcome-to-docker/` directory in the project

### Symptom

A `welcome-to-docker/` folder appears in the repo and `docker build .`
in the project root says "Dockerfile: no such file or directory".

### Why

That folder is the official Docker tutorial repo cloned by hand;
unrelated to this project. Our Dockerfiles live in
`backend/Dockerfile` and `frontend/Dockerfile`, both wired into
`docker-compose.yml`.

### Fix

```powershell
Remove-Item -Recurse -Force welcome-to-docker
```

Always boot the project stack with `docker compose up -d --build`,
never with `docker build .`.

## ClickHouse refuses connections during first boot

### Symptom

`vector` keeps restarting; `make logs` shows ClickHouse "starting up"
for several minutes.

### Why

ClickHouse 24+ runs schema bootstrap and metadata migrations on first
boot. On a slow disk this can exceed the 50 s healthcheck window.

### Fix

Wait until `docker compose ps` shows clickhouse as `healthy`. If it
keeps cycling, drop the broken first boot:

```powershell
docker compose down
docker volume rm waf-panel_ch_data
docker compose up -d
```

## DVWA is `unhealthy`

### Symptom

`docker compose ps` shows `waf-dvwa` as `(unhealthy)`.

### Why

DVWA's healthcheck issues `wget -q -O- http://127.0.0.1/` which receives
a `302 → /login.php`. Some `wget` builds inside the DVWA image return
non-zero on a 3xx redirect, flipping the container to `unhealthy` even
though the app is live.

### Why this is not a blocker

`proxy` only depends on `dvwa: { condition: service_started }`, not
`service_healthy`. The proxy starts as soon as DVWA's PID 1 is up, and
traffic over `localhost:8080` works regardless of the verdict.

### Optional cosmetic fix

```yaml
test: ["CMD", "sh", "-c", "wget -q -O- --max-redirect=2 http://127.0.0.1/login.php >/dev/null || exit 1"]
```

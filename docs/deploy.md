# Demo deployment — Fly.io

> A 5-minute walkthrough that turns the local docker-compose stack into a
> public HTTPS URL. Suitable for recruiter demos, NOT production —
> ml-service / ClickHouse / Vector / DVWA are intentionally omitted to
> fit the free tier.

## What gets deployed

A single container that runs **nginx + uvicorn**:

- The React SPA (built statically; served by nginx at `/`).
- The FastAPI backend (uvicorn at `127.0.0.1:8000`, proxied by nginx
  at `/api/*`).
- Alembic migrations on boot, so the seeded admin user is present.

A managed **Fly Postgres** is attached at runtime through `DATABASE_URL`.
The startup script translates that env into the `POSTGRES_*` fields
`config.py` already understands, so no application code changes.

What the demo does NOT have:

- **ml-service** — the backend proxy fail-opens, the panel still works.
  Incidents render with the `ML unavailable` pill.
- **ClickHouse** — `Dashboard` charts render empty; the metrics endpoints
  return zeroes. Rules editor, audit log, and user management are fully
  functional.
- **DVWA + ModSec + Vector** — those are the protective edge, not part
  of the panel itself.

## One-time setup (the operator)

```bash
# Install flyctl from https://fly.io/docs/hands-on/install-flyctl/
brew install flyctl       # macOS / Linux
# or:
iwr https://fly.io/install.ps1 -useb | iex   # Windows PowerShell

# Sign up + log in.
fly auth signup           # opens a browser
fly auth login

# From the repo root:
cd "Web Application Firewall"
cp infra/deploy/fly.toml fly.toml
$EDITOR fly.toml          # set app = "your-app-name", primary_region = "<closest>"
```

## Deploy

```bash
# 1. Create the app + free Postgres.
fly apps create <YOUR-APP>
fly postgres create --name <YOUR-APP>-db --region <closest>
fly postgres attach <YOUR-APP>-db --app <YOUR-APP>

# 2. Required secret: JWT_SECRET. The startup guard refuses to boot
#    with a default secret in WAF_ENV=production.
fly secrets set JWT_SECRET=$(openssl rand -hex 32) --app <YOUR-APP>

# 3. Deploy.
fly deploy --app <YOUR-APP>

# 4. Get the URL.
fly info --app <YOUR-APP>
# https://<YOUR-APP>.fly.dev/
```

## First login

```
URL:      https://<YOUR-APP>.fly.dev/
Email:    admin@example.com
Password: admin
```

**Rotate the password immediately** before sharing the URL. The startup
guard does NOT block here because the seeded password is `admin` AND
the runtime env is production — but only if Alembic migrations ran.
To rotate:

```bash
fly postgres connect --app <YOUR-APP>-db
# inside psql:
\c waf_panel
UPDATE users SET password_hash = crypt('a-real-password', gen_salt('bf'))
  WHERE email = 'admin@example.com';
\q
```

(You can also rotate via the **Users** page after first login — it
preserves the hash format properly via `passlib.argon2`.)

## Custom domain (optional)

```bash
fly certs add panel.your-domain.com --app <YOUR-APP>
# Add the A / AAAA records Fly tells you to. SSL is provisioned in ~2 min.
```

After the cert lands, update `WAF_ENV`'s neighbours so the cookie path
matches:

```bash
fly secrets set CORS_ORIGINS='["https://panel.your-domain.com"]' --app <YOUR-APP>
```

## Recurring costs

On the Fly free tier (Hobby plan):

- 1 shared-cpu-1x machine with 256 MB RAM: **$0/mo** (free allowance).
- 1 Postgres cluster, 256 MB RAM, 1 GB volume: **$0/mo** (free allowance).
- Bandwidth: 160 GB outbound free.

Total: **$0/mo** for a low-traffic demo. Set `auto_stop_machines = "stop"`
in `fly.toml` (already configured) so the machine spins down when idle
and only wakes on a request.

## Tearing it down

```bash
fly apps destroy <YOUR-APP>          # the panel
fly postgres destroy <YOUR-APP>-db   # the database
```

## Troubleshooting

- **`alembic upgrade head` fails on first boot.** The `start.sh` script
  logs the failure and continues. Check `fly logs --app <YOUR-APP>` and
  re-run with `fly ssh console -C 'cd /app/backend && alembic upgrade head'`.
- **Login returns 500 with `JWT_SECRET` errors.** You forgot step 2.
  Set the secret and `fly deploy` again.
- **Dashboard cards all show `—`.** Expected — there's no ClickHouse
  in this deployment. The panel itself works.

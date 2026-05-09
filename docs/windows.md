# Running waf-panel on Windows

The project's `Makefile` is a convenience for Linux/macOS hosts. On Windows
all the same operations are available through `dev.ps1` in PowerShell, or
directly through `docker compose` if you prefer.

## Prerequisites

- Windows 10 or 11.
- Docker Desktop 4.30+ with the WSL 2 backend enabled.
- PowerShell 7+ (the bundled Windows PowerShell 5 also works for
  `dev.ps1`).
- Git for Windows (so `.gitattributes` enforces LF line endings on the
  files Docker mounts into Linux containers).

## Quick start

```powershell
cd "C:\Users\pante\Documents\Web Application Firewall"
copy .env.example .env

# preferred: the wrapper
.\dev.ps1 up
.\dev.ps1 ps
.\dev.ps1 migrate

# or pure docker compose
docker compose up -d --build
docker compose ps
docker compose exec backend alembic upgrade head
```

Open the panel:

- Frontend: <http://localhost:3000>
- Backend OpenAPI: <http://localhost:8000/api/docs>
- Protected target via WAF: <http://localhost:8080>

Default credentials for the panel: `admin@example.com` / `admin`.
Rotate from the API or psql before using the stack outside dev.

## dev.ps1 cheat-sheet

| Command                             | What it does                                              |
|-------------------------------------|-----------------------------------------------------------|
| `.\dev.ps1 up`                      | Build + start stack in the background.                    |
| `.\dev.ps1 ps`                      | Container status, healthchecks.                           |
| `.\dev.ps1 logs`                    | Tail combined logs (Ctrl-C to exit).                      |
| `.\dev.ps1 migrate`                 | `alembic upgrade head` inside the backend container.      |
| `.\dev.ps1 rebuild-frontend`        | No-cache rebuild + restart of the SPA image.              |
| `.\dev.ps1 backend-shell`           | Bash inside the backend container.                        |
| `.\dev.ps1 pg-shell`                | psql connected to `waf_panel`.                            |
| `.\dev.ps1 ch-shell`                | `clickhouse-client` against `waf_logs`.                   |
| `.\dev.ps1 down`                    | Stop containers, keep volumes.                            |
| `.\dev.ps1 nuke`                    | Confirm-prompted full cleanup. Drops volumes.             |

If PowerShell refuses to run the script, allow local scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Line endings

Windows defaults to CRLF. Some files in this repo are mounted directly
into Linux containers (`infra/nginx/templates/*.conf.template`,
`infra/vector/vector.toml`, `infra/postgres/init.sql`,
`scripts/smoke.sh`). The `.gitattributes` file pins these to LF so Git
checks them out correctly even on Windows. If you copy them in with
another tool and end up with CRLF, you will see strange parse errors
from nginx/Vector — re-clone or run:

```powershell
git rm --cached -r .
git reset --hard
```

## Common pitfalls

- **`docker build .` from the project root fails.** There is no
  Dockerfile at the root. Use `docker compose up -d --build`. See
  `docs/troubleshooting.md` for context.
- **`make` is not recognised.** Use `dev.ps1` or `docker compose`
  directly.
- **Frontend image build fails on `npm install`.** Already mitigated:
  the Dockerfile resolves dependencies fresh, and `package-lock.json`
  is excluded from the build context. See
  `docs/troubleshooting.md`.
- **DVWA image is amd64-only.** Will not run on Windows-on-ARM.
- **Port 8080 is already in use.** IIS or another local dev tool
  occupies it. Override in `.env`: `PROXY_PORT=18080`.

## What does not run on Windows directly

The host-side helpers `make smoke` / `.\dev.ps1 smoke` need a Linux
shell with `bash` + `curl`. PowerShell's wrapper invokes them inside
an alpine container so you do not need WSL just for the smoke check;
WSL is still required for Docker Desktop's engine.

Backend `pytest` and `ruff` will run on the host once you have
Python 3.11+ installed locally:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

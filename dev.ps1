# dev.ps1 — Windows equivalent of the Makefile targets.
# Usage:
#   .\dev.ps1 up         # docker compose up -d --build
#   .\dev.ps1 down       # docker compose down
#   .\dev.ps1 ps
#   .\dev.ps1 logs
#   .\dev.ps1 smoke      # runs scripts/smoke.sh inside an alpine container
#   .\dev.ps1 migrate
#   .\dev.ps1 test       # backend unit tests on the host
#   .\dev.ps1 lint
#   .\dev.ps1 nuke       # WARNING: drops volumes
#
# WHY: Make is not standard on Windows. PowerShell handles the same verbs.

[CmdletBinding()]
param(
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet('up','down','restart','ps','logs','smoke','migrate','ch-migrate','bootstrap','test','lint','rebuild-frontend','rebuild-ml-service','vendor-ml','backend-shell','pg-shell','ch-shell','nuke','train','train-register','ml-test','ml-lint','ml-svc-test','ml-svc-lint','ml-promote','drift-check','help')]
    [string]$Command = 'help'
)

function Invoke-Compose($ComposeArgs) {
    # WHY: splatting the args keeps quoting sane.
    # WHY $ComposeArgs (not $Args): $Args collides with PowerShell's
    # automatic $args variable, which makes splatting flaky depending
    # on call site (works for `Invoke-Compose @(...)` standalone but
    # silently empties when chained with `;`).
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Sync-WafMl {
    # WHY: ml-service/Dockerfile expects ./waf_ml/ next to itself
    #      ("Vendored waf_ml package — one source of truth"), but the
    #      package actually lives in ml/src/waf_ml/. We don't commit the
    #      copy — every `up` / `build` re-syncs it from source so the
    #      online inferencer can never drift from the trainer's
    #      featurizer. .dockerignore in ml-service/ excludes it from any
    #      other build context.
    $src = Join-Path $PSScriptRoot 'ml/src/waf_ml'
    $dst = Join-Path $PSScriptRoot 'ml-service/waf_ml'
    if (-not (Test-Path $src)) {
        Write-Host "ERROR: ml/src/waf_ml not found at $src" -ForegroundColor Red
        exit 1
    }
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Path $src -Destination $dst -Recurse -Force
    Write-Host "vendored waf_ml -> $dst" -ForegroundColor DarkGray
}

switch ($Command) {
    'help' {
        @"
waf-panel — Windows dev runner

Targets:
  up                 Build & start the stack in the background.
  down               Stop containers, keep volumes.
  restart            down + up.
  ps                 docker compose ps.
  logs               Tail combined logs (Ctrl-C to exit).
  smoke              Run the smoke script against the running stack.
  migrate            Apply alembic upgrade head inside the backend container.
  ch-migrate         Re-apply infra/clickhouse/init.sql (CH views) idempotently.
  bootstrap          First-time setup: migrate + ch-migrate (Sprint 14).
  test               Run backend pytest on the host (needs Python 3.11+).
  lint               Run ruff on the backend on the host.
  rebuild-frontend   Force a no-cache rebuild of the frontend image.
  rebuild-ml-service Force a no-cache rebuild of the ml-service image (re-vendors waf_ml).
  vendor-ml          Just sync ml/src/waf_ml -> ml-service/waf_ml (no Docker).
  backend-shell      Bash inside the backend container.
  pg-shell           psql connected to waf_panel.
  ch-shell           clickhouse-client connected to waf_logs.
  nuke               docker compose down -v  (DESTROYS DB volumes).
  train              Offline ML pipeline on synthetic data → ml/models/<version>/.
  train-register     Train + register all models in Postgres; mark XGBoost active.
  ml-test            Run ml/ unit tests.
  ml-lint            Run ruff on ml/.

Examples:
  .\dev.ps1 up
  .\dev.ps1 ps
  .\dev.ps1 migrate
  .\dev.ps1 train
"@ | Write-Host
    }

    'up'                 { Sync-WafMl; Invoke-Compose @('up','-d','--build') }
    'down'               { Invoke-Compose @('down') }
    'restart'            { Invoke-Compose @('down'); Sync-WafMl; Invoke-Compose @('up','-d','--build') }
    'ps'                 { Invoke-Compose @('ps') }
    'logs'               { Invoke-Compose @('logs','-f','--tail=200') }
    'rebuild-frontend'   { Invoke-Compose @('build','--no-cache','frontend'); Invoke-Compose @('up','-d') }
    'rebuild-ml-service' { Sync-WafMl; Invoke-Compose @('build','--no-cache','ml-service'); Invoke-Compose @('up','-d','ml-service') }
    'vendor-ml'          { Sync-WafMl }
    'migrate'            { Invoke-Compose @('exec','backend','alembic','upgrade','head') }

    'ch-migrate' {
        # WHY: ClickHouse's docker-entrypoint runs *.sql once, on first
        # volume init. If init.sql changes after that, the running CH
        # never picks it up. This target re-applies init.sql idempotently
        # — every CREATE in it is `IF NOT EXISTS`, so it's safe to run
        # against an already-initialized stack.
        Write-Host 'Applying infra/clickhouse/init.sql to ClickHouse…' -ForegroundColor DarkGray
        & docker cp infra/clickhouse/init.sql waf-clickhouse:/tmp/init.sql
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Invoke-Compose @(
            'exec', 'clickhouse', 'clickhouse-client',
            '--user', 'waf', '--password', 'waf_dev_only',
            '--multiquery', '--queries-file=/tmp/init.sql'
        )
        Write-Host 'ClickHouse migrations applied.' -ForegroundColor Green
    }

    'bootstrap' {
        # First-time-stack helper: wraps the manual sequence we discovered
        # the hard way during Sprint 13 smoke. Idempotent — safe to run
        # again if you suspect partial init.
        Write-Host '[1/3] alembic upgrade head (postgres schema + admin seed)' -ForegroundColor Cyan
        Invoke-Compose @('exec','backend','alembic','upgrade','head')
        Write-Host '[2/3] ch-migrate (clickhouse views)' -ForegroundColor Cyan
        & docker cp infra/clickhouse/init.sql waf-clickhouse:/tmp/init.sql | Out-Null
        Invoke-Compose @(
            'exec', 'clickhouse', 'clickhouse-client',
            '--user', 'waf', '--password', 'waf_dev_only',
            '--multiquery', '--queries-file=/tmp/init.sql'
        )
        Write-Host '[3/3] done. Login with admin@example.com / admin at http://localhost:3000' -ForegroundColor Green
    }
    'backend-shell'      { Invoke-Compose @('exec','backend','/bin/bash') }
    'pg-shell'           { Invoke-Compose @('exec','postgres','psql','-U','waf','-d','waf_panel') }
    'ch-shell'           { Invoke-Compose @('exec','clickhouse','clickhouse-client','--user','waf','--password','waf_dev_only','-d','waf_logs') }

    'smoke' {
        # WHY: smoke.sh expects bash + curl. Easiest portable way: run it
        #      inside a throwaway alpine container that joins the project network.
        Invoke-Compose @('run','--rm','--network=waf-panel_wafnet','--entrypoint','sh','proxy','-c',
            'apk add --quiet bash curl >/dev/null && bash /workspace/scripts/smoke.sh',
            '-v', "${PWD}:/workspace")
    }

    'test' {
        Push-Location backend
        try   { python -m pytest -q }
        finally { Pop-Location }
    }

    'lint' {
        Push-Location backend
        try   { ruff check src tests }
        finally { Pop-Location }
    }

    'nuke' {
        Write-Host "About to drop ALL project volumes. Type 'yes' to confirm." -ForegroundColor Yellow
        $confirm = Read-Host
        if ($confirm -ne 'yes') { Write-Host 'aborted'; return }
        Invoke-Compose @('down','-v')
    }

    'train' {
        Push-Location ml
        try   { python -m waf_ml.train --dataset synthetic }
        finally { Pop-Location }
    }

    'train-register' {
        Push-Location ml
        try   { python -m waf_ml.train --dataset synthetic --register --activate xgboost }
        finally { Pop-Location }
    }

    'ml-test' {
        Push-Location ml
        try   { python -m pytest -q }
        finally { Pop-Location }
    }

    'ml-lint' {
        Push-Location ml
        try   { ruff check src tests }
        finally { Pop-Location }
    }

    'ml-svc-test' {
        Push-Location ml-service
        try   { python -m pytest -q }
        finally { Pop-Location }
    }

    'ml-svc-lint' {
        Push-Location ml-service
        try   { ruff check src tests }
        finally { Pop-Location }
    }

    'ml-promote' {
        # WHY: copy the latest trained version dir to ml/models/active so the
        #      ml-service container picks it up on the next restart.
        $latest = Get-ChildItem ml/models -Directory -Filter 'v*' -ErrorAction SilentlyContinue |
                  Sort-Object Name | Select-Object -Last 1
        if (-not $latest) { Write-Host 'no trained models in ml/models'; exit 1 }
        $dst = 'ml/models/active'
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse $latest.FullName $dst
        Write-Host "promoted $($latest.FullName) -> $dst"
    }

    'drift-check' {
        # Sprint 11 — run one drift check inside the backend container.
        Invoke-Compose @('exec','backend','python','-m','waf_panel.workers.drift_worker')
    }
}

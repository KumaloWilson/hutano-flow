# Start the whole demonstration stack with one command on Windows:
#   scripts\demo_up.cmd        (or: powershell -ExecutionPolicy Bypass -File scripts\demo_up.ps1)
# Windows equivalent of scripts/demo_up.sh. Requires Docker Desktop with Compose v2.
# First run on a fresh clone: creates .env from .env.example with random local secrets.
# An existing .env is never changed. Fictional/synthetic data only; loopback ports only.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'Docker Desktop is required: https://docs.docker.com/desktop/setup/install/windows-install/'
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Write-Error 'Docker Compose v2 is required (docker compose ...). Start Docker Desktop and try again.' }

function New-Secret {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

if (-not (Test-Path '.env')) {
    $secret = New-Secret; $owner = New-Secret; $app = New-Secret
    $lines = Get-Content '.env.example' | ForEach-Object {
        $line = $_ -replace '^SECRET_KEY=.*', "SECRET_KEY=$secret"
        $line = $line.Replace('change-this-local-password', $owner)
        $line.Replace('change-this-app-password', $app)
    }
    # UTF-8 without a byte-order mark and LF endings, exactly as Docker Compose expects.
    [System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
    Write-Host 'Created .env with random local secrets (kept for later runs; never commit it).'
}

Write-Host 'Building and starting the database, API, worker and web app...'
docker compose up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { Write-Error "Start-up failed. See: docker compose logs" }

Write-Host @'

Hutano Flow is running (research prototype; fictional data; not for clinical use).
  Web app:  http://localhost:3000   (choose Hutano Community Clinic and a role)
  API docs: http://localhost:8000/docs
Research results finish a few minutes after start-up; the Overview shows when they are ready.
Walkthrough: docs\CLINIC_DEMO.md   Stop: docker compose down
'@

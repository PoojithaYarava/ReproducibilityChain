$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Host "Created .env. Set JWT_SECRET and keep all wallet keys local."
}

Push-Location (Join-Path $root "frontend")
npm.cmd ci
Pop-Location

Push-Location (Join-Path $root "blockchain")
npm.cmd ci
Pop-Location

Push-Location (Join-Path $root "backend")
py -3 -m venv .venv
& (Join-Path $root "backend\.venv\Scripts\python.exe") -m pip install -e ".[dev]"
Pop-Location

Write-Host "Dependencies installed. Follow README.md to deploy the local contract and start each service."

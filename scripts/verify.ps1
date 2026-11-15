$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $root "backend")
if (Test-Path ".venv\Scripts\python.exe") {
    & ".venv\Scripts\python.exe" -m pytest
} else {
    python -m pytest
}
Pop-Location

Push-Location (Join-Path $root "blockchain")
npm.cmd test
Pop-Location

Push-Location (Join-Path $root "frontend")
npm.cmd run build
Pop-Location

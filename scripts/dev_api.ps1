# Run the API (or the synthetic seed) on this machine for development (B8a). SYNTHETIC DATA ONLY.
#
#   scripts\dev_api.ps1               API on 127.0.0.1:8000, database swasthyoid_dev, M10 emergency access OFF
#   scripts\dev_api.ps1 -Seed         seed swasthyoid_dev once (python -m swasthyoid.devtools.seed), then exit
#   scripts\dev_api.ps1 -Emergency    ISOLATED M10 test setup: API on 127.0.0.1:8010, database swasthyoid_dev_m10,
#                                     EMERGENCY_ACCESS_ENABLED=1. Never the normal demo. Not a clinical or legal approval.
#
# Secrets come from user-level environment variables made by scripts\dev_setup.ps1; nothing is read from the repo.
param([switch]$Emergency, [switch]$Seed, [int]$Port = 0)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

function Get-Dev([string]$name) {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if (-not $value) { throw "$name is not set: run scripts\dev_setup.ps1 first" }
    return $value
}

$env:PII_KEY = Get-Dev "SWASTHYOID_DEV_PII_KEY"
$env:DOCUMENT_KEY = Get-Dev "SWASTHYOID_DEV_DOCUMENT_KEY"
$env:EXTRACTION_KEY = Get-Dev "SWASTHYOID_DEV_EXTRACTION_KEY"
$env:HMAC_KEY = Get-Dev "SWASTHYOID_DEV_HMAC_KEY"
$env:JWT_SECRET = Get-Dev "SWASTHYOID_DEV_JWT_SECRET"
$env:APP_ENV = "development"
$env:DEV_LOG_CODES = "1"  # one-time codes go to this process's log (APP_ENV=development only; api/deps.py)
Remove-Item Env:SWASTHYOID_TEST_MODE_CONFIRM, Env:EMERGENCY_ACCESS_ENABLED -ErrorAction SilentlyContinue

# DEVELOPMENT-ONLY technical values so the workflows can be clicked through. They are NOT the production values and NOT
# a clinical, legal or policy approval: TIMELINE_CONSENT_HOURS is DECISION-PENDING and ASSIST_SESSION_MINUTES is
# REVIEWER-PENDING (production stays unset: 503 not_configured until the owner and the clinical reviewer decide).
$env:TIMELINE_CONSENT_HOURS = "24"
$env:ASSIST_SESSION_MINUTES = "30"

if ($Emergency) {
    $env:DATABASE_URL = Get-Dev "SWASTHYOID_DEV_M10_DATABASE_URL"
    $env:DOCUMENT_STORE = Join-Path (Get-Dev "SWASTHYOID_DEV_DOCUMENT_STORE") "documents-m10"
    $env:EMERGENCY_ACCESS_ENABLED = "1"
    if ($Port -eq 0) { $Port = 8010 }
} else {
    $env:DATABASE_URL = Get-Dev "SWASTHYOID_DEV_DATABASE_URL"
    $env:DOCUMENT_STORE = Join-Path (Get-Dev "SWASTHYOID_DEV_DOCUMENT_STORE") "documents"
    if ($Port -eq 0) { $Port = 8000 }
}
New-Item -ItemType Directory -Force $env:DOCUMENT_STORE | Out-Null
Set-Location $root

if ($Seed) {
    & $py -m swasthyoid.devtools.seed
    exit $LASTEXITCODE
}
& $py -m uvicorn swasthyoid.api.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE

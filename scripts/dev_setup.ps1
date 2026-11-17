# One-time local development setup (B8a; owner decisions 1 and 2, 2026-11-17). SYNTHETIC DATA ONLY.
#
# Creates two local PostgreSQL databases next to the test database named in the user-level DATABASE_URL:
#   swasthyoid_dev      the normal demo (M10 emergency access OFF)
#   swasthyoid_dev_m10  an isolated database used only when the API runs with -Emergency (scripts/dev_api.ps1)
# and generates development-only secrets as user-level environment variables (SWASTHYOID_DEV_*). Nothing is written to
# the repository and no secret is printed. Existing values are kept, so running it again is safe.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$base = [Environment]::GetEnvironmentVariable("DATABASE_URL", "User")
if (-not $base) { throw "the user-level DATABASE_URL is not set (B0)" }

function Set-IfMissing([string]$name, [scriptblock]$make) {
    if ([Environment]::GetEnvironmentVariable($name, "User")) { Write-Output "kept $name"; return }
    [Environment]::SetEnvironmentVariable($name, (& $make), "User")
    Write-Output "set  $name"
}

$fernet = { & $py -I -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" }
$hex = { & $py -I -c "import secrets; print(secrets.token_hex(32))" }
Set-IfMissing "SWASTHYOID_DEV_PII_KEY" $fernet
Set-IfMissing "SWASTHYOID_DEV_DOCUMENT_KEY" $fernet
Set-IfMissing "SWASTHYOID_DEV_EXTRACTION_KEY" $fernet
Set-IfMissing "SWASTHYOID_DEV_HMAC_KEY" $hex
Set-IfMissing "SWASTHYOID_DEV_JWT_SECRET" $hex
Set-IfMissing "SWASTHYOID_DEV_DOCUMENT_STORE" { Join-Path $env:LOCALAPPDATA "swasthyoid-dev" }

$env:SWASTHYOID_SETUP_BASE = $base
foreach ($pair in @(@("swasthyoid_dev", "SWASTHYOID_DEV_DATABASE_URL"), @("swasthyoid_dev_m10", "SWASTHYOID_DEV_M10_DATABASE_URL"))) {
    $env:SWASTHYOID_SETUP_DB = $pair[0]
    & $py -I -c @"
import os, psycopg
from psycopg.conninfo import make_conninfo
base, name = os.environ['SWASTHYOID_SETUP_BASE'], os.environ['SWASTHYOID_SETUP_DB']
with psycopg.connect(base, autocommit=True) as c:
    if not c.execute('SELECT 1 FROM pg_database WHERE datname = %s', [name]).fetchone():
        c.execute(f'CREATE DATABASE {name}')
        print('created database', name)
    else:
        print('kept database', name)
"@
    if ($LASTEXITCODE -ne 0) { throw "could not create $($pair[0])" }
    Set-IfMissing $pair[1] { & $py -I -c "import os; from psycopg.conninfo import make_conninfo; print(make_conninfo(os.environ['SWASTHYOID_SETUP_BASE'], dbname=os.environ['SWASTHYOID_SETUP_DB']))" }
}
Remove-Item Env:SWASTHYOID_SETUP_BASE, Env:SWASTHYOID_SETUP_DB
Write-Output "done. Next: scripts\dev_api.ps1 -Seed, then start the API (scripts\dev_api.ps1)."

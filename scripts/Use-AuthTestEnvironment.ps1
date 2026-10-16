$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$repositoryEnvironment = Join-Path $repositoryRoot ".env"
$environmentFile = Join-Path $repositoryRoot ".local-data\authentication-test.env"

if (Test-Path -LiteralPath $repositoryEnvironment -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $repositoryEnvironment) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
            continue
        }
        $separator = $line.IndexOf("=")
        if ($separator -lt 1) { continue }
        $name = $line.Substring(0, $separator)
        $value = $line.Substring($separator + 1)
        if ($name -match '^(POSTGRES_[A-Z0-9_]+|EVENTFLOW_(DATABASE_URL|TEST_DATABASE_URL))$' -and $value) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
foreach ($line in Get-Content -LiteralPath $environmentFile) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
        continue
    }
    $separator = $line.IndexOf("=")
    if ($separator -lt 1) {
        throw "Malformed authentication environment entry."
    }
    $name = $line.Substring(0, $separator)
    $value = $line.Substring($separator + 1)
    if ($name -notmatch '^(EVENTFLOW|KEYCLOAK|POSTGRES)_[A-Z0-9_]+$') {
        throw "Unexpected authentication environment variable name."
    }
    if ($value) {
        Set-Item -Path "Env:$name" -Value $value
    }
}
} else {
    throw "Authentication environment not found. Run scripts/prepare_auth_test_environment.py first."
}

# Realm configuration is version-controlled; never use a local realm export as
# the source even when an older shared env file contains that former path.
$env:KEYCLOAK_REALM_IMPORT_FILE = "./infra/keycloak/realm-eventflow-test.json"

Write-Output "Loaded local EventFlow authentication settings into this PowerShell session. Secret values were not displayed."

#Requires -Version 5.1
<#
.SYNOPSIS
    Creates a GCP project, enables Gmail API, creates a service account,
    and generates a JSON key for the S/MIME Workspace Sync tool.
.PARAMETER ProjectId
    Globally unique GCP project ID. Format: [a-z][a-z0-9-]{4,28}[a-z0-9]
.PARAMETER ServiceAccountName
    Service account name. Defaults to "smime-sync-bot".
.PARAMETER KeyOutputPath
    Where to save credentials.json. Defaults to ".\credentials.json".
    WARNING: Contains a private key — never commit to source control.
.EXAMPLE
    .\create_gcp.ps1 -ProjectId "my-smime-sync-prod"
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9\-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [Parameter(Mandatory = $false)]
    [string]$ServiceAccountName = "smime-sync-bot",

    [Parameter(Mandatory = $false)]
    [string]$KeyOutputPath = ".\credentials.json"
)

$ErrorActionPreference = "Stop"

# Refresh PATH so gcloud is found after fresh install
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","Machine")

function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " GCP Project & Service Account Creator   "
Write-Host "=========================================" -ForegroundColor Cyan

# Preflight: gcloud installed?
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Fail "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
}

# Preflight: authenticated?
$activeAccount = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null
if (-not $activeAccount) { Fail "No active gcloud account. Run: gcloud auth login" }
Write-Host "Authenticated as: $activeAccount" -ForegroundColor Green

# Preflight: key output must not exist
if (Test-Path $KeyOutputPath) {
    Fail "'$KeyOutputPath' already exists. Remove it or specify a different -KeyOutputPath."
}

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

Write-Host "`nAbout to create:" -ForegroundColor Yellow
Write-Host "  GCP Project     : $ProjectId"
Write-Host "  Service Account : $saEmail"
Write-Host "  Key Output      : $KeyOutputPath"
Write-Host ""
$confirm = Read-Host "Proceed? [y/N]"
if ($confirm -notmatch '^[Yy]$') { Write-Host "Aborted." -ForegroundColor Yellow; exit 0 }

# Step 1: Create project
Write-Host "`nStep 1: Creating GCP project '$ProjectId'..." -ForegroundColor Yellow
gcloud projects create $ProjectId --name="SMIME Sync Project"
if ($LASTEXITCODE -ne 0) { Fail "Project creation failed." }

# Step 2: Set active project
Write-Host "Step 2: Setting active project..." -ForegroundColor Yellow
gcloud config set project $ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Could not set project." }

# Step 3: Enable Gmail API
Write-Host "Step 3: Enabling Gmail API (may take ~60 s)..." -ForegroundColor Yellow
gcloud services enable gmail.googleapis.com --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Failed to enable Gmail API." }

# Step 4: Create service account
Write-Host "Step 4: Creating service account '$ServiceAccountName'..." -ForegroundColor Yellow
gcloud iam service-accounts create $ServiceAccountName `
    --display-name="SMIME Sync Bot" --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Service account creation failed." }

# Step 5: Wait for propagation
Write-Host "Step 5: Waiting 15 s for SA propagation..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

# Step 6: Generate JSON key
Write-Host "Step 6: Generating credentials key..." -ForegroundColor Yellow
gcloud iam service-accounts keys create $KeyOutputPath `
    --iam-account=$saEmail --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Key generation failed." }

if (-not (Test-Path $KeyOutputPath)) { Fail "Key file was not written." }
$json = Get-Content $KeyOutputPath -Raw | ConvertFrom-Json
if (-not $json.client_id) { Fail "Key file exists but client_id is missing." }

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " SUCCESS" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Client ID : $($json.client_id)" -ForegroundColor Yellow
Write-Host "  Key saved : $(Resolve-Path $KeyOutputPath)" -ForegroundColor Yellow
Write-Host ""
Write-Host "REQUIRED NEXT STEPS:" -ForegroundColor Cyan
Write-Host "  1. Google Admin Console > Security > API Controls"
Write-Host "     > Manage Domain-Wide Delegation > Add new"
Write-Host "  2. Paste Client ID above. Grant BOTH scopes:"
Write-Host "     https://www.googleapis.com/auth/gmail.settings.basic"
Write-Host "     https://www.googleapis.com/auth/gmail.settings.sharing"
Write-Host "  3. Add key file to .gitignore. Never commit it."
Write-Host "  4. DWD changes take up to 20 min to propagate." -ForegroundColor Yellow

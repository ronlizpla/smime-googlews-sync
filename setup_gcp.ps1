#Requires -Version 5.1
<#
.SYNOPSIS
    Provisions the Google Cloud resources required by the S/MIME sync tool:
    (optionally) a GCP project, the Gmail API, a service account, and a JSON key.

.DESCRIPTION
    Single, fully parameterized entry point — nothing is hardcoded to any company,
    project, or domain. Safe to re-run: an existing project / service account is
    detected and reused rather than recreated.

    After running this you must, ONE TIME, authorize Domain-Wide Delegation for the
    printed Client ID in the Google Admin Console (instructions are printed at the end).

.PARAMETER ProjectId
    Globally unique GCP project ID. Format: [a-z][a-z0-9-]{4,28}[a-z0-9]

.PARAMETER ServiceAccountName
    Short account id for the service account. Default: "smime-sync-bot".

.PARAMETER KeyOutputPath
    Where to write the service account JSON key. Default: ".\credentials.json".
    WARNING: contains a private key — never commit it to source control.

.PARAMETER CreateProject
    Create the GCP project with the given ProjectId. Omit to use an existing project.

.EXAMPLE
    .\setup_gcp.ps1 -ProjectId acme-smime-12345 -CreateProject

.EXAMPLE
    .\setup_gcp.ps1 -ProjectId existing-project -ServiceAccountName smime-bot -KeyOutputPath C:\keys\acme.json
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9\-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [string]$ServiceAccountName = "smime-sync-bot",

    [string]$KeyOutputPath = ".\credentials.json",

    [switch]$CreateProject
)

$ErrorActionPreference = "Stop"

# Refresh PATH from registry so a freshly-installed gcloud is found
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "Machine")

function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " S/MIME GCP Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Preflight: gcloud installed?
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Fail "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
}

# Preflight: authenticated?
$activeAccount = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null
if (-not $activeAccount) { Fail "No active gcloud account. Run: gcloud auth login" }
Write-Host "Authenticated as: $activeAccount" -ForegroundColor Green

# Preflight: key output must not already exist (avoid key sprawl / accidental overwrite)
if (Test-Path $KeyOutputPath) {
    Fail "'$KeyOutputPath' already exists. Remove it or specify a different -KeyOutputPath."
}

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

Write-Host ""
Write-Host "Plan:" -ForegroundColor Yellow
Write-Host "  GCP Project     : $ProjectId"
Write-Host "  Service Account : $saEmail"
Write-Host "  Key Output      : $KeyOutputPath"
Write-Host "  Create Project  : $($CreateProject.IsPresent)"
Write-Host ""

# Step 1: Create project (optional, idempotent)
if ($CreateProject) {
    Write-Host "Step 1: Creating GCP project '$ProjectId'..." -ForegroundColor Yellow
    $exists = gcloud projects list --filter="projectId:$ProjectId" --format="value(projectId)" 2>$null
    if ($exists -eq $ProjectId) {
        Write-Host "  Project already exists - skipping creation." -ForegroundColor Green
    } else {
        gcloud projects create $ProjectId --name="S/MIME Sync Project"
        if ($LASTEXITCODE -ne 0) { Fail "Project creation failed." }
    }
} else {
    Write-Host "Step 1: Using existing project '$ProjectId'." -ForegroundColor Yellow
}

# Step 2: Set active project
Write-Host "Step 2: Setting active project..." -ForegroundColor Yellow
gcloud config set project $ProjectId | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Could not set project '$ProjectId'." }

# Step 3: Enable Gmail API
Write-Host "Step 3: Enabling Gmail API (may take ~60 s)..." -ForegroundColor Yellow
gcloud services enable gmail.googleapis.com --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Failed to enable Gmail API." }

# Step 4: Create service account (idempotent)
Write-Host "Step 4: Creating service account '$ServiceAccountName'..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts list --project=$ProjectId `
    --filter="email:$saEmail" --format="value(email)" 2>$null
if ($saExists -eq $saEmail) {
    Write-Host "  Service account already exists - skipping." -ForegroundColor Green
} else {
    gcloud iam service-accounts create $ServiceAccountName `
        --display-name="S/MIME Sync Bot" --project=$ProjectId
    if ($LASTEXITCODE -ne 0) { Fail "Service account creation failed." }
    Write-Host "  Waiting 15 s for propagation..." -ForegroundColor Yellow
    Start-Sleep -Seconds 15
}

# Step 5: Generate JSON key
Write-Host "Step 5: Generating credentials key -> '$KeyOutputPath'..." -ForegroundColor Yellow
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
Write-Host "REQUIRED NEXT STEPS (one time):" -ForegroundColor Cyan
Write-Host "  1. Google Admin Console > Security > Access and data control > API controls"
Write-Host "     > Manage Domain-Wide Delegation > Add new"
Write-Host "  2. Client ID:  $($json.client_id)"
Write-Host "  3. OAuth Scopes (comma-separated):"
Write-Host "       https://www.googleapis.com/auth/gmail.settings.basic,https://www.googleapis.com/auth/gmail.settings.sharing"
Write-Host "  4. Authorize (DWD changes take up to 20 min to propagate)." -ForegroundColor Yellow
Write-Host "  5. Keep '$KeyOutputPath' SECRET - it is already covered by .gitignore." -ForegroundColor Red

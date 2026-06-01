#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ProjectId         = "smime-cert-sync",
    [string]$ServiceAccountName = "smime-sync-bot",
    [string]$KeyOutputPath     = ".\credentials.json"
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","Machine")

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Fail "gcloud CLI not found."
}
if (Test-Path $KeyOutputPath) {
    Fail "'$KeyOutputPath' already exists. Remove it first."
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Configuring Project: $ProjectId"
Write-Host "==========================================" -ForegroundColor Cyan

# Step 1: Set active project
Write-Host "Step 1: Setting project..." -ForegroundColor Yellow
gcloud config set project $ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Could not set project." }

# Step 2: Enable Gmail API
Write-Host "Step 2: Enabling Gmail API..." -ForegroundColor Yellow
gcloud services enable gmail.googleapis.com --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Failed to enable Gmail API." }

# Step 3: Create SA (idempotent)
Write-Host "Step 3: Creating service account '$ServiceAccountName'..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts list --project=$ProjectId `
    --filter="email:$saEmail" --format="value(email)" 2>$null
if ($saExists -match $ServiceAccountName) {
    Write-Host "  Service account already exists — skipping." -ForegroundColor Green
} else {
    gcloud iam service-accounts create $ServiceAccountName `
        --display-name="SMIME Sync Bot" --project=$ProjectId
    if ($LASTEXITCODE -ne 0) { Fail "Service account creation failed." }
    Write-Host "  Waiting 15 s for propagation..." -ForegroundColor Yellow
    Start-Sleep -Seconds 15
}

# Step 4: Generate JSON key
Write-Host "Step 4: Generating credentials.json key..." -ForegroundColor Yellow
gcloud iam service-accounts keys create $KeyOutputPath `
    --iam-account=$saEmail --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Key generation failed." }

if (-not (Test-Path $KeyOutputPath)) { Fail "Key file was not written." }
$json = Get-Content $KeyOutputPath -Raw | ConvertFrom-Json
if (-not $json.client_id) { Fail "client_id missing in key file." }

Write-Host "==========================================" -ForegroundColor Green
Write-Host " SUCCESS: credentials.json created!"       -ForegroundColor Green
Write-Host " Client ID: $($json.client_id)"            -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Keep '$KeyOutputPath' SECRET. Add to .gitignore." -ForegroundColor Red

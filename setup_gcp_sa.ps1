# Refresh PATH from registry so gcloud is available
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$env:Path = "$userPath;$machinePath"

$projId = "smime-cert-sync"
$saName = "smime-sync-bot"
$saEmail = "$saName@$projId.iam.gserviceaccount.com"
$keyFile = "credentials.json"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Configuring Project: $projId"
Write-Host "=========================================" -ForegroundColor Cyan

# Step 1: Set active project
Write-Host "Step 1: Setting active gcloud project to '$projId'..." -ForegroundColor Yellow
gcloud config set project $projId

# Step 2: Enable Gmail API
Write-Host "Step 2: Enabling Gmail API..." -ForegroundColor Yellow
gcloud services enable gmail.googleapis.com --project=$projId

# Step 3: Create Service Account (skip if exists)
Write-Host "Step 3: Creating Service Account '$saName'..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts list --project=$projId --filter="email:$saEmail" --format="value(email)" 2>$null
if ($saExists -match $saName) {
    Write-Host "  Service account already exists. Skipping."
} else {
    gcloud iam service-accounts create $saName --display-name="SMIME Sync Bot" --project=$projId
}

# Step 4: Generate JSON key
Write-Host "Step 4: Generating credentials.json key file..." -ForegroundColor Yellow
gcloud iam service-accounts keys create $keyFile --iam-account=$saEmail --project=$projId

if (Test-Path $keyFile) {
    $json = Get-Content $keyFile -Raw | ConvertFrom-Json
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host "SUCCESS: credentials.json created!" -ForegroundColor Green
    Write-Host "Client ID: $($json.client_id)" -ForegroundColor Yellow
    Write-Host "=========================================" -ForegroundColor Green
} else {
    Write-Host "ERROR: credentials.json was NOT created." -ForegroundColor Red
    Write-Host "Check if the org policy 'iam.disableServiceAccountKeyCreation' is still enforced on project $projId" -ForegroundColor Red
    exit 1
}

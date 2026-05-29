$ErrorActionPreference = "Stop"

# Refresh PATH from registry to pick up newly installed gcloud
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$env:Path = "$userPath;$machinePath"

$projId = "smime-sync-mieteora-54812"

Write-Host "========================================="
Write-Host "GCP Project & Service Account Creator"
Write-Host "========================================="

# Create Project
Write-Host "Step 1: Creating GCP Project '$projId'..."
gcloud projects create $projId --name="SMIME Sync Project"

# Set Config
Write-Host "Step 2: Setting active gcloud project to '$projId'..."
gcloud config set project $projId

# Enable API
Write-Host "Step 3: Enabling Gmail API (this may take a minute)..."
gcloud services enable gmail.googleapis.com

# Create Service Account
Write-Host "Step 4: Creating Service Account 'smime-sync-bot'..."
gcloud iam service-accounts create smime-sync-bot --display-name="SMIME Sync Bot"

# Generate JSON Key
Write-Host "Step 5: Generating and downloading credentials.json key file..."
gcloud iam service-accounts keys create credentials.json --iam-account="smime-sync-bot@${projId}.iam.gserviceaccount.com"

Write-Host "========================================="
Write-Host "SUCCESS: credentials.json created in project directory!"
Write-Host "========================================="

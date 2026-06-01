#Requires -Version 5.1
param(
    [string]$ProjectId          = "smime-cert-sync",
    [string]$ServiceAccountName = "smime-sync-bot",
    [string]$KeyOutputPath      = ".\credentials.json"
)

$ErrorActionPreference = "Stop"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","Machine")

function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Fail "gcloud CLI not found."
}
if (Test-Path $KeyOutputPath) {
    Fail "'$KeyOutputPath' already exists. Remove it first to avoid key sprawl."
}

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"

Write-Host "Waiting 10 s for SA propagation..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

Write-Host "Creating credentials key..." -ForegroundColor Yellow
gcloud iam service-accounts keys create $KeyOutputPath `
    --iam-account=$saEmail --project=$ProjectId
if ($LASTEXITCODE -ne 0) { Fail "Key creation failed." }

if (Test-Path $KeyOutputPath) {
    $json = Get-Content $KeyOutputPath -Raw | ConvertFrom-Json
    if ($json.client_id) {
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "SUCCESS: credentials.json created."        -ForegroundColor Green
        Write-Host "Client ID: $($json.client_id)"             -ForegroundColor Yellow
        Write-Host "==========================================" -ForegroundColor Green
    } else {
        Fail "File created but client_id is missing or empty."
    }
} else {
    Fail "credentials.json was not written."
}

# Refresh PATH so gcloud is available
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")

Write-Host "Waiting 10 seconds for SA propagation..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

Write-Host "Creating credentials.json key..." -ForegroundColor Yellow
gcloud iam service-accounts keys create credentials.json `
    --iam-account="smime-sync-bot@smime-cert-sync.iam.gserviceaccount.com" `
    --project=smime-cert-sync

if (Test-Path credentials.json) {
    $json = Get-Content credentials.json -Raw | ConvertFrom-Json
    if ($json.client_id) {
        Write-Host "=========================================" -ForegroundColor Green
        Write-Host "SUCCESS! credentials.json created." -ForegroundColor Green
        Write-Host "Client ID: $($json.client_id)" -ForegroundColor Yellow
        Write-Host "=========================================" -ForegroundColor Green
    } else {
        Write-Host "File created but appears empty/invalid." -ForegroundColor Red
    }
} else {
    Write-Host "ERROR: credentials.json not found." -ForegroundColor Red
}

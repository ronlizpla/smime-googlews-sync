param(
    [string[]]$Emails = @("ron@mieteora.com", "test@mieteora.com", "test1@mieteora.com", "test2@mieteora.com"),
    [string]$Password = "Mieteora2026!"
)

# 1. Find OpenSSL binary
$openssl = "openssl"
if (-not (Get-Command $openssl -ErrorAction SilentlyContinue)) {
    $gitOpenSsl = "C:\Program Files\Git\usr\bin\openssl.exe"
    if (Test-Path $gitOpenSsl) {
        $openssl = $gitOpenSsl
    } else {
        Write-Error "OpenSSL is not installed in path and was not found at standard Git path ($gitOpenSsl)."
        Exit 1
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = "." }
$confFile = Join-Path $scriptDir "openssl.conf"

if (-not (Test-Path $confFile)) {
    Write-Error "Configuration file openssl.conf not found at $confFile."
    Exit 1
}

# 2. Ensure Root CA exists, if not generate it
$caKey = Join-Path $scriptDir "ca.key"
$caCrt = Join-Path $scriptDir "ca.crt"
if (-not (Test-Path $caKey) -or -not (Test-Path $caCrt)) {
    Write-Host "Creating Root CA..."
    & $openssl req -x509 -new -nodes -newkey rsa:4096 -keyout $caKey -out $caCrt -days 3650 -subj "/CN=Mieteora Test Root CA/O=Mieteora/C=US" -config $confFile -extensions ca_ext
}

# Create output directory for Workspace API packages
$outputDir = Join-Path $scriptDir "workspace_packages"
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

Write-Host "Generating packages in: $outputDir"

foreach ($email in $Emails) {
    $username = $email.Split('@')[0]
    $cn = $username.Substring(0,1).ToUpper() + $username.Substring(1) + " Mieteora"
    
    Write-Host "`n--------------------------------------------------"
    Write-Host "Processing User: $cn ($email)"
    Write-Host "--------------------------------------------------"

    # Setup temporary files for generation
    $userKey = Join-Path $outputDir "$username.key"
    $userCsr = Join-Path $outputDir "$username.csr"
    $userCrt = Join-Path $outputDir "$username.crt"
    $userPfx = Join-Path $outputDir "$username.pfx"
    $jsonFile = Join-Path $outputDir "import_$username.json"

    # Set env variable for SAN
    $env:SMIME_EMAIL = $email

    # Generate User Cert
    & $openssl genrsa -out $userKey 2048
    & $openssl req -new -key $userKey -out $userCsr -subj "/CN=$cn/emailAddress=$email/O=Mieteora/C=US" -config $confFile
    & $openssl x509 -req -in $userCsr -CA $caCrt -CAkey $caKey -CAcreateserial -out $userCrt -days 365 -extfile $confFile -extensions smime_ext
    & $openssl pkcs12 -export -out $userPfx -inkey $userKey -in $userCrt -certfile $caCrt -passout "pass:$Password"

    # Clean up intermediate csr/key/crt files if we only need PFX/JSON, or keep them?
    # Let's keep them so the user has full access to the keys and raw certs as well.

    # 3. Read PFX, encode to base64url, and write JSON
    $pfxBytes = [System.IO.File]::ReadAllBytes($userPfx)
    $base64 = [System.Convert]::ToBase64String($pfxBytes)
    # Convert base64 to base64url: Replace + with -, / with _, and remove padding =
    $base64Url = $base64.Replace('+', '-').Replace('/', '_').Replace('=', '')

    $jsonObj = @{
        pkcs12 = $base64Url
        encryptedKeyPassword = $Password
    }

    $jsonObj | ConvertTo-Json -Compress | Out-File -FilePath $jsonFile -Encoding utf8

    Write-Host "Successfully generated API import payload: $jsonFile"
}

Write-Host "`n======================================================="
Write-Host "All certificates and Google Workspace API JSON packages generated!"
Write-Host "Import them using Gmail API: users.settings.sendAs.smimeInfo.insert"
Write-Host "======================================================="

param(
    [string]$Email = "testuser@example.com",
    [string]$CommonName = "Test User",
    [string]$Password = "password"
)

# 1. Find OpenSSL binary
$openssl = "openssl"
if (-not (Get-Command $openssl -ErrorAction SilentlyContinue)) {
    # Check Git's default installation path
    $gitOpenSsl = "C:\Program Files\Git\usr\bin\openssl.exe"
    if (Test-Path $gitOpenSsl) {
        $openssl = $gitOpenSsl
    } else {
        Write-Error "OpenSSL is not installed in path and was not found at standard Git path ($gitOpenSsl)."
        Write-Host "Please install Git or OpenSSL, or run the script using PowerShell's native cmdlet instead."
        Exit 1
    }
}

Write-Host "Using OpenSSL from: $openssl"

# 2. Setup paths and environment variables
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = "." }
$confFile = Join-Path $scriptDir "openssl.conf"

if (-not (Test-Path $confFile)) {
    Write-Error "Configuration file openssl.conf not found at $confFile."
    Exit 1
}

# Set the environment variable for OpenSSL SAN extension
$env:SMIME_EMAIL = $Email

Write-Host "Generating certificates for $CommonName ($Email)..."

# 3. Generate Certificate Authority (CA)
Write-Host "`n--- Generating Root CA ---"
& $openssl req -x509 -new -nodes -newkey rsa:4096 -keyout ca.key -out ca.crt -days 3650 -subj "/CN=Test Root CA/O=Test CA Org/C=US" -config $confFile -extensions ca_ext

# 3.5. Generate Intermediate CA
Write-Host "`n--- Generating Intermediate CA ---"
& $openssl genrsa -out intermediate.key 4096
& $openssl req -new -key intermediate.key -out intermediate.csr -subj "/CN=Test Intermediate CA/O=Test CA Org/C=US" -config $confFile
& $openssl x509 -req -in intermediate.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out intermediate.crt -days 1825 -extfile $confFile -extensions intermediate_ext

# 4. Generate User Key and Certificate Request (CSR)
Write-Host "`n--- Generating User CSR ---"
& $openssl genrsa -out user.key 2048
& $openssl req -new -key user.key -out user.csr -subj "/CN=$CommonName/emailAddress=$Email/O=Test User Org/C=US" -config $confFile

# 5. Sign the User CSR using the Intermediate CA
Write-Host "`n--- Signing Certificate with Intermediate CA ---"
& $openssl x509 -req -in user.csr -CA intermediate.crt -CAkey intermediate.key -CAcreateserial -out user.crt -days 365 -extfile $confFile -extensions smime_ext

# 6. Package user cert & key as a PKCS#12 (PFX) file
Write-Host "`n--- Packaging into PFX ---"
Get-Content intermediate.crt, ca.crt | Out-File chain.crt -Encoding utf8
& $openssl pkcs12 -export -out user.pfx -inkey user.key -in user.crt -certfile chain.crt -passout "pass:$Password"

Write-Host "`n======================================================="
Write-Host "S/MIME Test Certificate generation complete!"
Write-Host "Files generated in: $scriptDir"
Write-Host "  - ca.crt        : Trust this certificate in your Google Workspace Admin Console"
Write-Host "  - intermediate.crt: Intermediate CA certificate"
Write-Host "  - user.crt      : User public certificate"
Write-Host "  - user.key      : User private key"
Write-Host "  - user.pfx      : Combined certificate + key + chain (password: '$Password')"
Write-Host "                    Import this file into Gmail / Outlook / Thunderbird."
Write-Host "======================================================="


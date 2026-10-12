# Sign the built executables with a code-signing certificate. Uses only built-in Windows tooling.
#
#   .\sign.ps1 -Thumbprint <thumbprint of a code-signing cert in your Windows certificate store>
#   .\sign.ps1 -Pfx C:\path\cert.pfx            (password is read from the PLUNGE_PFX_PASSWORD environment variable)
#
# A real certificate must be bought from a certificate authority (or a service such as Azure Trusted Signing); it needs
# identity verification, so only you can do that. An unsigned or self-signed file still triggers Windows SmartScreen.
# Signing the installer is what matters most: sign dist\Plunge.exe, dist\plunge-cli.exe, THEN build the installer,
# THEN sign the installer.  build.ps1 -Sign does this order for you.
param(
  [string]$Thumbprint,
  [string]$Pfx,
  [string]$Timestamp = "http://timestamp.digicert.com",
  [string[]]$Files = @("dist\Plunge.exe", "dist\plunge-cli.exe")
)
Set-Location $PSScriptRoot

if ($Thumbprint) {
  $cert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object { $_.Thumbprint -eq $Thumbprint } | Select-Object -First 1
} elseif ($Pfx) {
  if (-not $env:PLUNGE_PFX_PASSWORD) { throw "Set PLUNGE_PFX_PASSWORD (do not put the password on the command line)." }
  $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($Pfx, $env:PLUNGE_PFX_PASSWORD)
} else { throw "Give -Thumbprint or -Pfx." }
if (-not $cert) { throw "Certificate not found." }
if (-not ($cert.EnhancedKeyUsageList.ObjectId -contains "1.3.6.1.5.5.7.3.3")) { throw "That certificate is not a code-signing certificate." }

foreach ($f in $Files) {
  if (-not (Test-Path $f)) { Write-Warning "skip (missing): $f"; continue }
  $r = Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $Timestamp
  "{0,-28} {1}" -f $f, $r.Status
  if ($r.Status -ne "Valid" -and $r.Status -ne "UnknownError") { Write-Warning $r.StatusMessage }
}

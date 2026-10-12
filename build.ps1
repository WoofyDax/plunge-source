# Builds dist\Plunge.exe (the app), dist\plunge-cli.exe (console twin) and dist\PlungeSetup-<version>.exe (installer).
# Needs: python -m pip install pywebview pyinstaller pillow   and Inno Setup 6 (winget install JRSoftware.InnoSetup --source winget)
#   .\build.ps1                      build everything
#   .\build.ps1 -Sign <thumbprint>   also sign (exes first, then the installer)
param([string]$Sign)
Set-Location $PSScriptRoot
Get-Process Plunge -ErrorAction SilentlyContinue | Stop-Process -Force
$version = (Select-String -Path core\version.py -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
if (-not (Test-Path assets\plunge.ico)) { python tools\make_icon.py }

python -m PyInstaller --noconfirm --clean --onefile --noconsole --name Plunge --icon assets\plunge.ico --add-data "ui;ui" --add-data "legal;legal" --distpath dist --workpath build app.py
python -m PyInstaller --noconfirm --onefile --console --name plunge-cli --icon assets\plunge.ico --exclude-module webview --add-data "legal;legal" --distpath dist --workpath build-cli app.py
if ($Sign) { .\sign.ps1 -Thumbprint $Sign }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
  & $iscc "/DAppVersion=$version" installer\plunge.iss
  if ($Sign) { .\sign.ps1 -Thumbprint $Sign -Files @("dist\PlungeSetup-$version.exe") }
} else { Write-Warning "Inno Setup not found: skipped the installer." }
Get-ChildItem dist\*.exe | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }

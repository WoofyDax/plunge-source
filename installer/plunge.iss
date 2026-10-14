; Inno Setup script for Plunge. Per-user install (no admin prompt). Build with ..\build.ps1.
#define AppName "Plunge"
#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif
#define Publisher "Plunge (plungevr.com)"

[Setup]
AppId={{B6C1E2D4-5A3F-4C7B-9E21-6D0A8F3C1B57}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\{#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PlungeSetup-{#AppVersion}
SetupIconFile=..\assets\plunge.ico
UninstallDisplayIcon={app}\Plunge.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\legal\TERMS.md

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "protocol"; Description: "Open plunge:// join links with Plunge (so friends' invite links work)"

[Files]
Source: "..\dist\Plunge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\plunge-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\legal\*.md"; DestDir: "{app}\legal"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Plunge.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Plunge.exe"; Tasks: desktopicon

[Registry]
; per-user, only when the player ticks the box; removed again on uninstall
Root: HKCU; Subkey: "Software\Classes\plunge"; ValueType: string; ValueData: "URL:Plunge"; Flags: uninsdeletekey; Tasks: protocol
Root: HKCU; Subkey: "Software\Classes\plunge"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: protocol
Root: HKCU; Subkey: "Software\Classes\plunge\shell\open\command"; ValueType: string; ValueData: """{app}\Plunge.exe"" ""%1"""; Tasks: protocol

[Run]
Filename: "{app}\Plunge.exe"; Description: "Open Plunge"; Flags: nowait postinstall skipifsilent

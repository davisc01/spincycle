; Inno Setup script -- packages build.ps1's PyInstaller onedir output
; (dist\Spin Cycle\Spin Cycle.exe + dist\Spin Cycle\_internal\...) into a
; normal Windows installer: Program Files install, Start Menu shortcut,
; uninstaller registered in Add/Remove Programs.
;
; Run via build.ps1 (locates ISCC.exe and calls it after the PyInstaller
; build), or directly once dist\Spin Cycle\ already exists:
;
;     iscc installer.iss

#define MyAppName "Spin Cycle"
#define MyAppExeName "Spin Cycle.exe"

[Setup]
; Fixed once and never changed -- this is what lets a future installer
; version upgrade/replace this one cleanly instead of Windows treating it
; as an unrelated app.
AppId={{6E9F2D3E-6B0C-4B77-9C0A-6C5C6E6B7A11}
AppName={#MyAppName}
AppVersion=1.0
AppPublisher=Spin Cycle
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Spin Cycle-Windows-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\Spin Cycle\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

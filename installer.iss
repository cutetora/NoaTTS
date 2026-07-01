; ============================================================
;  NoaTTS Inno Setup installer script
;  Wraps the THIN portable build (dist\NoaTTS-portable\) into a
;  double-click NoaTTS-Setup.exe.
;
;  Build steps:
;    1) build_portable.bat            (creates dist\NoaTTS-portable\)
;    2) Open this file in Inno Setup Compiler (https://jrsoftware.org/isdl.php)
;       and press "Compile"  ->  Output\NoaTTS-Setup.exe
;
;  Notes:
;   - Installs into {localappdata}\NoaTTS so NO admin rights are needed
;     AND the first-run setup can write torch/deps into python\ later.
;     (Program Files would be read-only for the first-run pip install.)
;   - The app stays "THIN": first launch still runs first_run_setup.bat
;     to download torch (auto-CUDA) + models. Keep that for portability.
; ============================================================

#define MyAppName "NoaTTS"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "cutetora"
#define MyAppURL "https://github.com/cutetora/NoaTTS"
; Prefer the icon'd exe launcher; the bat is also installed as a fallback.
#define MyAppExeName "NoaTTS.exe"
#define MyPortableDir "dist\NoaTTS-portable"

[Setup]
AppId={{B7A3C1E2-9D4F-4A6B-8C5D-NOATTS0000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; Install per-user into LocalAppData (writable; needed for first-run pip install)
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=NoaTTS-Setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\noa.ico
UninstallDisplayIcon={app}\assets\noa.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; Bundle the entire THIN portable folder (Python + app + launchers).
Source: "{#MyPortableDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Start Menu + Desktop shortcuts point at the launcher (.bat).
; pythonw.exe is launched by the bat; the shortcut shows the app icon.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\noa.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\noa.ico"; Tasks: desktopicon

[Run]
; Offer to launch right after install (first launch downloads torch+models).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove runtime-generated files so uninstall leaves nothing behind.
Type: filesandordirs; Name: "{app}\output"
Type: filesandordirs; Name: "{app}\__pycache__"

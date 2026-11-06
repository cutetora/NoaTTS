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
#define MyAppVersion "1.4.2"
#define MyAppPublisher "cutetora"
#define MyAppURL "https://github.com/cutetora/NoaTTS"
; Prefer the icon'd exe launcher; the bat is also installed as a fallback.
#define MyAppExeName "NoaTTS.exe"
; ビルド元フォルダ。ローカル試験では ISCC /DMyPortableDir=... で差し替えられる。
#ifndef MyPortableDir
#define MyPortableDir "dist\NoaTTS-portable"
#endif

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
; 更新で上書きされると困るユーザーデータは同梱しない (ボイスの config.json、conf\settings.json、
; gap.txt などはそもそも配布物に入っていない)。読み辞書だけは配布物に入っていて、利用者が追記する
; ファイルなので、無いときだけ置く (将来の版で既定の辞書が増えても、既存の利用者には反映されない)。
Source: "{#MyPortableDir}\*"; DestDir: "{app}"; Excludes: "conf\reading_dict.json"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#MyPortableDir}\conf\reading_dict.json"; DestDir: "{app}\conf"; Flags: onlyifdoesntexist
; 更新・アンインストール前にアプリを止めるスクリプト (インストーラー実行中は {tmp} に展開して使う)
Source: "installer\stop_app.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "installer\stop_app.ps1"; Flags: dontcopy
; 更新で requirements.txt が変わったときに、依存ライブラリを入れるスクリプト (下の [Code] から呼ぶ)
Source: "installer\update_deps.py"; DestDir: "{app}\scripts"; Flags: ignoreversion

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

[Code]
// 更新前のアプリ停止 (installer\stop_app.ps1) と、依存ライブラリの更新。
var
  OldReqHash: String;

// 引数のスクリプトで、{app} 配下で動いているアプリを止める。止まらなくても失敗にはしない
// (その場合は Inno Setup 標準の「使用中のアプリ」確認に任せる)。
procedure StopRunningApp(const Script: String);
var
  Rc: Integer;
begin
  if not FileExists(Script) then
  begin
    Log('stop_app.ps1 not found: ' + Script);
    Exit;
  end;
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -AppDir "' + RemoveBackslash(ExpandConstant('{app}')) + '"',
          '', SW_HIDE, ewWaitUntilTerminated, Rc) then
    Log('stop_app.ps1 exit code: ' + IntToStr(Rc))
  else
    Log('stop_app.ps1 could not be started: ' + SysErrorMessage(Rc));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  ExtractTemporaryFile('stop_app.ps1');
  StopRunningApp(ExpandConstant('{tmp}\stop_app.ps1'));
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  StopRunningApp(ExpandConstant('{app}\scripts\stop_app.ps1'));
end;

// requirements.txt が変わった更新では、新しい依存ライブラリを入れる (scripts\update_deps.py)。
// - 初回セットアップ (torch の導入) が済んでいる環境でだけ行う。torch が無い環境で入れると、
//   CPU 版の torch が入って動かなくなるため。torch 自体は update_deps.py が版を固定して守る。
// - 「最後に依存を入れ終えた requirements.txt のハッシュ」を python\.req_sha256 に持つ。update_deps.py が
//   成功したときだけ書き換えるので、pip が失敗した更新は、インストーラーを再実行すると再試行される。
//   印が無い環境 (v1.4.0 以前から更新) は、上書き前の requirements.txt のハッシュを印にする。
procedure CurStepChanged(CurStep: TSetupStep);
var
  Req, Py, Stamp, Script, Cmd: String;
  Saved: AnsiString;
  Rc: Integer;
  Show: Integer;
  HasTorch: Boolean;
begin
  Req := ExpandConstant('{app}\requirements.txt');
  Py := ExpandConstant('{app}\python\python.exe');
  Stamp := ExpandConstant('{app}\python\.req_sha256');
  HasTorch := FileExists(Py) and DirExists(ExpandConstant('{app}\python\Lib\site-packages\torch'));
  if CurStep = ssInstall then
  begin
    if HasTorch and FileExists(Req) and not FileExists(Stamp) then
      SaveStringToFile(Stamp, GetSHA256OfFile(Req), False);
  end
  else if CurStep = ssPostInstall then
  begin
    if HasTorch and FileExists(Req) and FileExists(Stamp) and LoadStringFromFile(Stamp, Saved) and
       (Trim(String(Saved)) <> GetSHA256OfFile(Req)) then
    begin
      Log('requirements.txt changed; running scripts\update_deps.py');
      Script := ExpandConstant('{app}\scripts\update_deps.py');
      Cmd := '-I "' + Script + '" "' + RemoveBackslash(ExpandConstant('{app}')) + '"';
      if WizardSilent then Show := SW_HIDE else Show := SW_SHOWNORMAL;
      if not Exec(Py, Cmd, ExpandConstant('{app}'), Show, ewWaitUntilTerminated, Rc) or (Rc <> 0) then
      begin
        Log('update_deps.py failed, code ' + IntToStr(Rc));
        SuppressibleMsgBox('依存ライブラリの更新に失敗しました。ネットワークと git の有無を確認して、もう一度インストーラーを実行してください。',
                           mbError, MB_OK, IDOK);
      end;
    end;
  end;
end;

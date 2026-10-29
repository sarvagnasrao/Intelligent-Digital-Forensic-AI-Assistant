; IDFA installer (Inno Setup 6).
;
; Build on a machine with Inno Setup 6 installed:
;   winget install --id JRSoftware.InnoSetup -e
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\idfa.iss
;
; The result is dist\IDFA-<version>-setup.exe. It installs per user (no admin),
; ships the prepared offline cache in packages\ plus the model weights in
; models\ollama\, and then runs SETUP_IDFA.bat -Offline so the target machine
; never needs the network.
;
; Everything created at run time (.venv, tools\qdrant, the data folder) lives
; outside what the installer owns, so uninstalling never touches case data.

#define AppName "IDFA"
#define AppVersion "0.1.0"
#define AppPublisher "KSIT Bengaluru"
#define AppURL "https://github.com/"

[Setup]
AppId={{6F1A9C62-3C7E-4D5B-9E1A-7C6B2D8E4F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppURL}
DefaultDirName={localappdata}\Programs\IDFA
DefaultGroupName=IDFA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=IDFA-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName} {#AppVersion}
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; Application source. Compiled byte code and test output are never shipped.
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\worker\*"; DestDir: "{app}\worker"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\migrations\*"; DestDir: "{app}\migrations"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\icons\*"; DestDir: "{app}\icons"; Flags: recursesubdirs createallsubdirs ignoreversion

Source: "..\alembic.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\INSTALL_LOCAL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SETUP_IDFA.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\START_IDFA.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\STOP_IDFA.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\UNINSTALL_IDFA.bat"; DestDir: "{app}"; Flags: ignoreversion

; Offline payload: wheels, the Qdrant archive, OllamaSetup.exe and the marker.
Source: "..\packages\*"; DestDir: "{app}\packages"; Flags: recursesubdirs createallsubdirs ignoreversion

; Model weights imported into the user's Ollama store by setup.ps1.
Source: "..\models\ollama\*"; DestDir: "{app}\models\ollama"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Start IDFA"; Filename: "{app}\START_IDFA.bat"; WorkingDir: "{app}"
Name: "{group}\Stop IDFA"; Filename: "{app}\STOP_IDFA.bat"; WorkingDir: "{app}"
Name: "{group}\Verify installation"; Filename: "{app}\SETUP_IDFA.bat"; Parameters: "-Check"; WorkingDir: "{app}"
Name: "{group}\Uninstall IDFA"; Filename: "{uninstallexe}"
Name: "{autodesktop}\IDFA"; Filename: "{app}\START_IDFA.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; The cache is bundled, so setup never reaches the network. It creates .venv,
; installs the wheels, extracts Qdrant, imports the models and migrates the DB.
; -NoShortcuts: the installer creates its own Start Menu/Desktop entries.
Filename: "{app}\SETUP_IDFA.bat"; Parameters: "-Offline -NoShortcuts"; WorkingDir: "{app}"; Description: "Prepare IDFA now (recommended)"; Flags: postinstall shellexec

[UninstallRun]
; Stop the worker/Qdrant and remove the shortcuts setup may have created before
; the uninstaller deletes the files they run from.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop_idfa.ps1"""; Flags: runhidden; RunOnceId: "StopIdfaServices"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\install_shortcuts.ps1"" -Remove -Quiet"; Flags: runhidden; RunOnceId: "RemoveIdfaShortcuts"

[UninstallDelete]
; Created by setup, not by the installer. The data folder (%APPDATA%\IDFA and
; the chosen case root) is deliberately left alone.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\packages\offline-manifest.json"

[Code]
function PythonIsAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  { py.exe ships with the python.org installer; a bare python.exe is the fallback. }
  Result := Exec('cmd.exe', '/C py -3.12 -c "import sys" 2>NUL', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Result then
    Result := Exec('cmd.exe', '/C python -c "import sys" 2>NUL', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not PythonIsAvailable() then
  begin
    if MsgBox('Python 3.12 was not found on this computer.' + #13#10#13#10 +
      'IDFA needs it before setup can continue. Install Python 3.12 (64-bit), ' +
      'then run SETUP_IDFA.bat from the Start menu.' + #13#10#13#10 +
      'Continue with the installation anyway?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

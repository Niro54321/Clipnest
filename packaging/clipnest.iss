; Clipnest installer for Inno Setup 6, built by packaging/build.py.
; Installs for the current user only (no admin prompt), into
; %LOCALAPPDATA%\Programs\Clipnest.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{21971EC4-3092-47D0-9674-89AA017A09FB}
AppName=Clipnest
AppVersion={#AppVersion}
AppVerName=Clipnest {#AppVersion}
AppPublisher=Niro54321
; SignPath checks the product name on what it signs
VersionInfoProductName=Clipnest
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Niro54321
VersionInfoDescription=Clipnest Setup
AppPublisherURL=https://github.com/Niro54321/Clipnest
AppSupportURL=https://github.com/Niro54321/Clipnest/issues
AppUpdatesURL=https://github.com/Niro54321/Clipnest/releases
DefaultDirName={autopf}\Clipnest
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=Clipnest-Setup-{#AppVersion}
SetupIconFile=..\build\clipnest.ico
UninstallDisplayIcon={app}\Clipnest.exe
UninstallDisplayName=Clipnest
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "ffmpeg"; Description: "Download FFmpeg with winget (needed for every download, about 100 MB)"; Check: NeedsFFmpeg

[Files]
Source: "..\dist\Clipnest\*"; DestDir: "{app}"; Excludes: "clipnest-selftest.exe"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Clipnest"; Filename: "{app}\Clipnest.exe"; AppUserModelID: "Niro54321.Clipnest"
Name: "{autodesktop}\Clipnest"; Filename: "{app}\Clipnest.exe"; Tasks: desktopicon; AppUserModelID: "Niro54321.Clipnest"

[Run]
Filename: "winget.exe"; Parameters: "install --id Gyan.FFmpeg --exact --source winget --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Downloading FFmpeg..."; Tasks: ffmpeg; Flags: runhidden waituntilterminated
Filename: "{app}\Clipnest.exe"; Description: "Start Clipnest now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Clipnest.exe /F"; Flags: runhidden; RunOnceId: "StopClipnest"

[Code]
function NeedsFFmpeg: Boolean;
begin
  Result := (FileSearch('ffmpeg.exe', GetEnv('PATH')) = '')
    and not FileExists(ExpandConstant('{localappdata}\Microsoft\WinGet\Links\ffmpeg.exe'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { An older Clipnest may be open; close it so its files can be replaced. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM Clipnest.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

; SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
; WaveMaterial's Windows installer: per user, no admin rights, into
; %LOCALAPPDATA%\Programs\WaveMaterial. Compiled by packaging/windows/build.py, which passes
; the defines below.

#ifndef AppVersion
  #error Pass /DAppVersion, /DNumericVersion, /DMinVCRedist, /DBundleDir, /DRepoDir and /DOutputDir.
#endif
#ifndef Compression
  #define Compression "lzma2/max"
#endif
#ifndef OutputName
  #define OutputName "WaveMaterial-" + AppVersion + "-windows-x86_64-setup"
#endif

[Setup]
AppId={{096E86A8-6E0B-4558-B361-0F11B820A3A1}
AppName=WaveMaterial
AppVersion={#AppVersion}
AppVerName=WaveMaterial {#AppVersion}
AppPublisher=s7u512
AppPublisherURL=https://github.com/s7u512/wavematerial
AppSupportURL=https://github.com/s7u512/wavematerial/issues
AppUpdatesURL=https://github.com/s7u512/wavematerial/releases
VersionInfoVersion={#NumericVersion}
VersionInfoProductName=WaveMaterial
DefaultDirName={autopf}\WaveMaterial
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#RepoDir}\LICENSE.md
SetupIconFile={#RepoDir}\design\logo\app-icon.ico
UninstallDisplayIcon={app}\wavematerial.ico
UninstallDisplayName=WaveMaterial
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression={#Compression}
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the runtime whole, so no files from an older version linger.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\WaveMaterial"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m wavematerial"; WorkingDir: "{app}"; IconFilename: "{app}\wavematerial.ico"; Comment: "Transcribe recordings and edit the transcripts"
Name: "{autodesktop}\WaveMaterial"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m wavematerial"; WorkingDir: "{app}"; IconFilename: "{app}\wavematerial.ico"; Comment: "Transcribe recordings and edit the transcripts"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m wavematerial"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,WaveMaterial}"; Flags: nowait postinstall skipifsilent

[Code]
// The bundle ships none of Microsoft's C++ runtime DLLs, so Windows must have the Visual C++
// Redistributable. It is found the way Microsoft documents: its registry key.
const
  VCRedistKey = 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  VCRedistPage = 'https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist';
  VCRedistDownload = 'https://aka.ms/vs/17/release/vc_redist.x64.exe';

function HasVCRedist(): Boolean;
var
  Installed, Major, Minor, Bld: Cardinal;
  Need: Int64;
begin
  Result := RegQueryDWordValue(HKLM64, VCRedistKey, 'Installed', Installed) and (Installed = 1)
    and RegQueryDWordValue(HKLM64, VCRedistKey, 'Major', Major)
    and RegQueryDWordValue(HKLM64, VCRedistKey, 'Minor', Minor)
    and RegQueryDWordValue(HKLM64, VCRedistKey, 'Bld', Bld)
    and StrToVersion('{#MinVCRedist}', Need)
    and (ComparePackedVersion(PackVersionComponents(Major, Minor, Bld, 0), Need) >= 0);
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := HasVCRedist();
  if not Result then begin
    Log('Visual C++ Redistributable (x64) {#MinVCRedist} or later not found.');
    if SuppressibleMsgBox('WaveMaterial needs the Microsoft Visual C++ Redistributable (x64), '
      + 'version {#MinVCRedist} or later, and it is not installed.' + #13#10#13#10
      + 'Download it from Microsoft:' + #13#10 + VCRedistDownload + #13#10
      + '(details: ' + VCRedistPage + ')' + #13#10#13#10
      + 'Installing it needs administrator rights. After installing it, run this installer '
      + 'again.' + #13#10#13#10 + 'Start the download now?',
      mbError, MB_YESNO, IDNO) = IDYES then
      ShellExec('open', VCRedistDownload, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;

// Uninstalling: offer to delete the speech models too (models only; transcripts and settings
// stay). The app notes its models folder in models-folder.txt in its data folder. Only a
// "WaveMaterial models" folder or the default one is ever deleted; a silent uninstall keeps
// them (an update never runs the uninstaller).
const
  ModelsFolderName = 'WaveMaterial models';

function DefaultModelsFolder(): String;
begin
  Result := ExpandConstant('{localappdata}\wavematerial\models');
end;

function ModelsFolder(): String;
var
  Lines: TArrayOfString;
begin
  Result := '';
  if LoadStringsFromFile(ExpandConstant('{localappdata}\wavematerial\models-folder.txt'), Lines)
    and (GetArrayLength(Lines) > 0) then
    Result := RemoveBackslashUnlessRoot(Trim(Lines[0]));
  if Result = '' then
    Result := DefaultModelsFolder();
end;

function SafeToDelete(Folder: String): Boolean;
begin
  Result := (CompareText(ExtractFileName(Folder), ModelsFolderName) = 0)
    or (CompareText(Folder, DefaultModelsFolder()) = 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Folder: String;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  Folder := ModelsFolder();
  if UninstallSilent() or not DirExists(Folder) or not SafeToDelete(Folder) then
    exit;
  if MsgBox('Also delete the speech models (2.9 GB) in' + #13#10 + Folder + '?' + #13#10#13#10
    + 'Your transcripts and settings are kept either way.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(Folder, True, True, True);
end;

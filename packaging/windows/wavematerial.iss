; SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
; WaveMaterial's Windows installer: per user, no admin rights, into
; %LOCALAPPDATA%\Programs\WaveMaterial. Compiled by packaging/windows/build.py, which passes
; the defines below.

#ifndef AppVersion
  #error Pass /DAppVersion, /DNumericVersion, /DBundleDir, /DRepoDir and /DOutputDir.
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
OutputBaseFilename=WaveMaterial-{#AppVersion}-windows-x86_64-setup
Compression=lzma2/max
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

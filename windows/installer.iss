#define AppVersion Trim(FileRead(FileOpen("..\VERSION")))
[Setup]
AppId={{E18CD762-45BB-42B5-9176-2FC3C49B9DA1}
AppName=Agent Sessions
AppVersion={#AppVersion}
AppPublisher=Agent Sessions contributors
AppPublisherURL=https://github.com/DenysIvko/agent-sessions
AppUpdatesURL=https://github.com/DenysIvko/agent-sessions/releases
DefaultDirName={localappdata}\Programs\Agent Sessions
DefaultGroupName=Agent Sessions
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Agent-Sessions-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AgentSessions.exe
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE

[Files]
Source: "..\build\windows\AgentSessions\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"

[Icons]
Name: "{group}\Agent Sessions"; Filename: "{app}\AgentSessions.exe"
Name: "{group}\Uninstall Agent Sessions"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\AgentSessions.exe"; Description: "Launch Agent Sessions"; Flags: nowait postinstall skipifsilent

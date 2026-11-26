#define AppVersion GetEnv('VIDEOBOT_VERSION')
[Setup]
AppName=VideoBot
AppVersion={#AppVersion}
AppId={{D61B3284-5C3E-40CC-9CAC-298B83E6DBA0}
DefaultDirName={localappdata}\Programs\VideoBot
DefaultGroupName=VideoBot
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VideoBot-{#AppVersion}-Windows-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\VideoBot.exe
[Files]
Source: "..\dist\VideoBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\VideoBot"; Filename: "{app}\VideoBot.exe"
Name: "{userdesktop}\VideoBot"; Filename: "{app}\VideoBot.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\VideoBot.exe"; Description: "Launch VideoBot"; Flags: nowait postinstall skipifsilent

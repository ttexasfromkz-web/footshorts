#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
[Setup]
AppId={{F3465DB5-B3DD-43A8-9070-43373D6AA1C7}
AppName=Football Shorts
AppVersion={#AppVersion}
AppPublisher=Football Shorts
DefaultDirName={localappdata}\FootballShorts
DefaultGroupName=Football Shorts
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=FootballShorts-Setup
SetupIconFile=..\dist\installer\FootballShorts\FootballShorts.ico
UninstallDisplayIcon={app}\FootballShorts.ico
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
[Files]
Source: "..\dist\installer\FootballShorts\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userdesktop}\Football Shorts"; Filename: "{app}\.runtime\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\FootballShorts.ico"
Name: "{group}\Football Shorts"; Filename: "{app}\.runtime\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\FootballShorts.ico"
Name: "{group}\Football Shorts - Repair"; Filename: "{app}\.runtime\python.exe"; Parameters: """{app}\runtime_manager.py"" --repair"; WorkingDir: "{app}"; IconFilename: "{app}\FootballShorts.ico"
[Run]
Filename: "{app}\.runtime\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; Description: "Launch Football Shorts"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: user projects/music are never recursively deleted.

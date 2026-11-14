; Inno Setup script for the Windows installer (built by .github/workflows/app.yml).
#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif

[Setup]
AppId={{6F0B8C1E-2A4D-4E8B-9C3F-1D7A5E2B4C60}
AppName=Nexonic IPTV
AppVersion={#AppVersion}
AppPublisher=Shahrukh Khalid
AppPublisherURL=https://github.com/Shahrukhalid/nexonic-iptv
AppSupportURL=https://github.com/Shahrukhalid/nexonic-iptv/issues
DefaultDirName={autopf}\Nexonic IPTV
DefaultGroupName=Nexonic IPTV
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutDir}
OutputBaseFilename=NexonicIPTV-Windows-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\NexonicIPTV.exe
LicenseFile={#LicenseFile}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Nexonic IPTV"; Filename: "{app}\NexonicIPTV.exe"
Name: "{autodesktop}\Nexonic IPTV"; Filename: "{app}\NexonicIPTV.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NexonicIPTV.exe"; Description: "Start Nexonic IPTV"; Flags: nowait postinstall skipifsilent

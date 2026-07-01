; 研策中枢 AlphaScope Windows installer
;
; Build:
;   python build.py --installer
;
; Output:
;   installer/installer-output/AlphaScope-Setup-1.9.39.exe

#define MyAppName "AlphaScope"
#define MyAppNameCN "研策中枢 AlphaScope"
#define MyAppVersion "1.9.39"
#define MyAppPublisher "TIANWEN"
#define MyAppURL "https://github.com/TIANWEN-cpu/AlphaScope"
#define MyAppExeName "AlphaScope.exe"
#define SourceDir "..\dist\AlphaScope"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppNameCN}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameCN} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppNameCN}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=installer-output
OutputBaseFilename=AlphaScope-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppNameCN} installer
VersionInfoProductName={#MyAppNameCN}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\db"; Flags: uninsneveruninstall
Name: "{app}\data\cache"; Flags: uninsneveruninstall
Name: "{app}\data\reports"; Flags: uninsneveruninstall
Name: "{app}\data\uploads"; Flags: uninsneveruninstall
Name: "{app}\data\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\停止 {#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{group}\{cm:UninstallProgram,{#MyAppNameCN}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppNameCN}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile: string;
  EnvExample: string;
begin
  if CurStep = ssPostInstall then
  begin
    EnvFile := ExpandConstant('{app}\.env');
    EnvExample := ExpandConstant('{app}\.env.example');
    if not FileExists(EnvFile) and FileExists(EnvExample) then
    begin
      FileCopy(EnvExample, EnvFile, False);
      MsgBox('安装完成！' + #13#10 + #13#10 +
             '双击桌面快捷方式即可启动。首次使用 AI 分析前，请在 .env 文件中填写模型 API Key：' + #13#10 +
             EnvFile,
             mbInformation, MB_OK);
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := MsgBox('确定要卸载 {#MyAppNameCN} 吗？' + #13#10 + #13#10 +
                   '本地数据目录 data/ 和 .env 配置文件会保留。',
                   mbConfirmation, MB_YESNO) = IDYES;
end;

; Hand2LaTeX 智能工作台 —— Inno Setup 6 安装脚本
;
; 一般不用手动运行：scripts\package.ps1 -BuildInstaller 会自动调用它，并传进三个参数。
; 手动编译（示例）：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" ^
;     /DAppVersion=1.0.0 ^
;     /DSourceDir=D:\latex\dist\staging\Hand2LaTeX-1.0.0-win64 ^
;     /DOutputDir=D:\latex\dist ^
;     D:\latex\installer\hand2latex.iss
;
; 注意：本文件必须保存成 "UTF-8 with BOM"，否则里面的中文在 Inno Setup 里会变成乱码。
; 注意：SourceDir 指向的是 package.ps1 生成的临时目录，里面已经有 BUILD_INFO.json、
;       安装说明.txt 和随包带的 vue.global.js。不要直接指向仓库根目录，
;       那样会把 .env（密钥）和 artifacts（本机任务）一起打进去。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\staging\Hand2LaTeX-0.0.0-win64"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define MyAppName "Hand2LaTeX 智能工作台"
#define MyAppPublisher "Hand2LaTeX"
#define MyAppBat "启动工作台.bat"

[Setup]
AppId={{8F4C2A1E-6B3D-4E57-9A02-1C7D5E3F2B41}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppComments=手写笔记照片转可编辑 LaTeX 与中文 PDF
; 装到用户自己的目录：程序要在安装目录里写 .venv、.env、artifacts\jobs，
; 装进 Program Files 会因为没有写权限而失败，所以这里不要求管理员权限。
DefaultDirName={localappdata}\Programs\Hand2LaTeX
DefaultGroupName=Hand2LaTeX
PrivilegesRequired=lowest
DisableProgramGroupPage=auto
OutputDir={#OutputDir}
OutputBaseFilename=Hand2LaTeX-{#AppVersion}-win64-setup
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=no
InfoBeforeFile={#SourceDir}\安装说明.txt
UninstallDisplayIcon={app}\tools\tectonic\tectonic.exe
UninstallDisplayName={#MyAppName}
SetupLogging=yes
WizardStyle=modern

[Languages]
; 如果你的 Inno Setup 6 里没有 ChineseSimplified.isl（少数精简安装会缺），
; 把下面这一行删掉即可，安装界面会变成英文，功能不受影响。
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppBat}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 13; Comment: "启动 Hand2LaTeX 智能工作台"
Name: "{group}\关闭工作台"; Filename: "{app}\关闭工作台.bat"; WorkingDir: "{app}"
Name: "{group}\安装说明"; Filename: "{app}\安装说明.txt"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppBat}"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 13; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppBat}"; Description: "立即启动工作台（首次启动会联网安装依赖，需要几分钟）"; WorkingDir: "{app}"; Flags: postinstall nowait shellexec skipifsilent
Filename: "{app}\.env"; Description: "打开 .env 填写 OPENAI_API_KEY（不填就不能识别）"; WorkingDir: "{app}"; Flags: postinstall nowait shellexec skipifsilent

[UninstallDelete]
; 虚拟环境和缓存是安装后生成的、体积很大，卸载时直接删掉。
; artifacts\jobs 是用户自己的历史任务，不在这里删——卸载向导会单独问要不要保留。
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\node_modules"

[Code]
// 安装包里不含 Python，也没有 Python 就跑不起来，所以装之前先体检一次并如实告知。
function IsPythonAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C python --version', '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsPythonAvailable() then
    MsgBox('没有检测到可用的 python 命令。' + #13#10 + #13#10 +
           'Hand2LaTeX 需要 Python 3.10 / 3.11 / 3.12（安装包里不含 Python）。' + #13#10 +
           '下载地址：https://www.python.org/downloads/windows/' + #13#10 +
           '安装时请勾选 "Add python.exe to PATH"。' + #13#10 + #13#10 +
           '现在可以继续安装，但装完要先装好 Python 才能启动。',
           mbInformation, MB_OK);
end;

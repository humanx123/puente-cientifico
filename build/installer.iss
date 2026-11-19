; Instalador de Puente Científico (Inno Setup 6)
; Lo compila build.ps1:  ISCC.exe /DAppVersion=1.0.0 installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Puente Científico"
#define AppId "PuenteCientifico"
#define StageDir AddBackslash(SourcePath) + "stage\PuenteCientifico"

[Setup]
AppId={{36129E01-EF68-440E-AB6B-B8F0A54EE37B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Puente Científico
AppComments=Biblioteca PDF, traducción con maquetación, literatura científica y noticias en español.
DefaultDirName={localappdata}\Programs\{#AppId}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#SourcePath}\dist
OutputBaseFilename={#AppId}-Setup-{#AppVersion}
SetupIconFile={#StageDir}\app\assets\puente.ico
UninstallDisplayIcon={app}\app\assets\puente.ico
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktop"; Description: "Crear icono en el escritorio"; GroupDescription: "Accesos directos:"

[InstallDelete]
; Limpia código de versiones anteriores (los datos del usuario viven en %APPDATA% y no se tocan)
Type: filesandordirs; Name: "{app}\app\puente"
Type: filesandordirs; Name: "{app}\app\static"

[UninstallDelete]
; Cachés .pyc que Python genera al ejecutarse (los datos del usuario en %APPDATA% se conservan)
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\tor"
Type: dirifempty; Name: "{app}"

[Files]
Source: "{#StageDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\tor\*"; DestDir: "{app}\tor"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\run.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\puente.ico"; Comment: "Leer, traducir y encontrar literatura científica"; AppUserModelID: "PuenteCientifico.App"
Name: "{group}\Diagnóstico de {#AppName}"; Filename: "{app}\runtime\python.exe"; Parameters: """{app}\app\diagnostico.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\puente.ico"
Name: "{group}\Abrir en el navegador"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\run.py"" --navegador"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\puente.ico"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\run.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\assets\puente.ico"; Tasks: desktop; AppUserModelID: "PuenteCientifico.App"

[Run]
; WebView2 (motor de la ventana): solo si falta. Windows 10/11 actualizados ya lo traen.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Write-Host 'Descargando Microsoft Edge WebView2...'; curl.exe -L --progress-bar -o '{tmp}\MicrosoftEdgeWebview2Setup.exe' 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'; Start-Process -FilePath '{tmp}\MicrosoftEdgeWebview2Setup.exe' -ArgumentList '/silent','/install' -Wait"""; StatusMsg: "Instalando WebView2 (necesario para la ventana)..."; Flags: waituntilterminated; Check: NeedWebView2
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\run.py"""; WorkingDir: "{app}\app"; Description: "Abrir {#AppName}"; Flags: postinstall nowait skipifsilent

[Code]
function NeedWebView2: Boolean;
var
  Version: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0') then
    Result := False;
  if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0') then
    Result := False;
end;

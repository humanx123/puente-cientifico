<#
  Compila Puente Científico para Windows:
    1. Interfaz React (Vite)            -> backend\static
    2. Python 3.11 embebido + deps      -> build\stage\PuenteCientifico\runtime
    3. Código de la app                 -> build\stage\PuenteCientifico\app
    4. Instalador Inno Setup            -> build\dist\PuenteCientifico-Setup-<versión>.exe

  Uso:  powershell -ExecutionPolicy Bypass -File build\build.ps1 [-SinInstalador] [-Limpio]
#>
param([switch]$SinInstalador, [switch]$Limpio)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Raiz   = Split-Path -Parent $PSScriptRoot
$Build  = $PSScriptRoot
$Cache  = Join-Path $Build "cache"
$Stage  = Join-Path $Build "stage\PuenteCientifico"
$Runtime = Join-Path $Stage "runtime"
$App    = Join-Path $Stage "app"
$PyVer  = "3.11.9"
$Version = (Select-String -Path "$Raiz\backend\puente\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value

function Paso($t) { Write-Host "`n=== $t ===" -ForegroundColor Yellow }
function Ejecutar($exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "Falló: $exe $($argumentos -join ' ')" }
}

New-Item -ItemType Directory -Force $Cache | Out-Null
if ($Limpio -and (Test-Path $Stage)) { Remove-Item -Recurse -Force $Stage }

# ---------------------------------------------------------------------------
Paso "1/5 Interfaz React"
Push-Location "$Raiz\frontend"
if (-not (Test-Path node_modules)) { cmd /c "npm ci --no-audit --no-fund 2>&1"; if ($LASTEXITCODE) { throw "npm ci falló" } }
cmd /c "npx vite build 2>&1"; if ($LASTEXITCODE) { throw "vite build falló" }
Pop-Location

# ---------------------------------------------------------------------------
Paso "2/5 Python $PyVer embebido"
$zip = Join-Path $Cache "python-$PyVer-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    curl.exe -L --fail -o $zip "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
    if ($LASTEXITCODE) { throw "No se pudo descargar Python embebido" }
}
if (-not (Test-Path "$Runtime\python.exe")) {
    New-Item -ItemType Directory -Force $Runtime | Out-Null
    Expand-Archive -Force $zip $Runtime
    # Rutas de importación: zip estándar, la carpeta de la app y site-packages
    Set-Content -Encoding ascii "$Runtime\python311._pth" "python311.zip`r`n.`r`n..\app`r`nLib\site-packages`r`nimport site`r`n"
    $getpip = Join-Path $Cache "get-pip.py"
    if (-not (Test-Path $getpip)) { curl.exe -L --fail -o $getpip "https://bootstrap.pypa.io/get-pip.py" }
    Ejecutar "$Runtime\python.exe" @("-s", $getpip, "--no-warn-script-location")
}

Paso "3/5 Dependencias en el runtime (aisladas del Python del sistema)"
Ejecutar "$Runtime\python.exe" @("-s", "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check", "-r", "$Raiz\backend\requirements.txt")
# Verificación con -s: si algo solo existiera en el user-site del desarrollador, aquí falla
Ejecutar "$Runtime\python.exe" @("-s", "-c", "import fastapi, uvicorn, multipart, webview, clr_loader, fitz, requests, socks, lxml, feedparser, bs4, pathvalidate; print('dependencias OK')")

# ---------------------------------------------------------------------------
Paso "4/5 Código de la app"
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force $App | Out-Null
foreach ($item in @("puente", "datos", "static", "server.py", "run.py", "diagnostico.py", "requirements.txt")) {
    Copy-Item -Recurse -Force "$Raiz\backend\$item" $App
}
New-Item -ItemType Directory -Force "$App\assets" | Out-Null
$PyDev = @("$Raiz\.venv\Scripts\python.exe", "$Raiz\..\..\..\.venv\Scripts\python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $PyDev) { $PyDev = "python" }
cmd /c "`"$PyDev`" -c `"import PIL`" >nul 2>nul"
if ($LASTEXITCODE) { cmd /c "`"$PyDev`" -m pip install -q pillow 2>&1" }
Ejecutar $PyDev @("$Build\icono.py", "$App\assets\puente.ico")

# Limpieza: cachés, pruebas y ejecutables sobrantes del runtime
Get-ChildItem -Recurse -Force -Directory $Stage -Include "__pycache__", "tests", "test" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\fitz\\|\\pymupdf\\" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Force "$Runtime\Scripts\*.exe" -ErrorAction SilentlyContinue

# Prueba de arranque del servidor con el runtime embebido (sin ventana)
$env:PUENTE_DATA_DIR = Join-Path $Cache "datos-prueba"
Remove-Item -Recurse -Force $env:PUENTE_DATA_DIR -ErrorAction SilentlyContinue
Ejecutar "$Runtime\python.exe" @("-s", "-c", "import sys; sys.path.insert(0, r'$App'); import os; os.chdir(r'$App'); from fastapi.testclient import TestClient; import server; c = TestClient(server.app); r = c.get('/api/estado'); assert r.status_code == 200, r.text; r = c.get('/'); assert b'root' in r.content; print('servidor OK', r.status_code)")
Remove-Item Env:\PUENTE_DATA_DIR

$tam = "{0:N0} MB" -f ((Get-ChildItem -Recurse $Stage | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Paquete preparado: $Stage ($tam)"

# ---------------------------------------------------------------------------
if ($SinInstalador) { exit 0 }
Paso "5/5 Instalador Inno Setup"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "C:\Program Files (x86)\Inno Setup 6\ISCC.exe", "C:\Program Files\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No encuentro Inno Setup 6 (ISCC.exe). Instálalo desde https://jrsoftware.org/isdl.php" }
Ejecutar $iscc @("/Q", "/DAppVersion=$Version", "$Build\installer.iss")
$exe = Join-Path $Build "dist\PuenteCientifico-Setup-$Version.exe"
Write-Host ("`nINSTALADOR: {0} ({1:N0} MB)" -f $exe, ((Get-Item $exe).Length / 1MB)) -ForegroundColor Green

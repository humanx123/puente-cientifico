"""Diagnóstico de Puente Científico: revisa paso a paso por qué la app no abre.
Se ejecuta con el Python de la app (runtime\\python.exe) y guarda un informe en el Escritorio."""
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import winreg

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
REPORT = os.path.join(DESKTOP, "diagnostico-puente-cientifico.txt")
MODULOS = ["fastapi", "uvicorn", "multipart", "webview", "clr_loader", "fitz", "requests", "socks", "lxml", "feedparser", "bs4",
           "pathvalidate", "libgen_api_enhanced"]


def _puerto_libre() -> int:
    for p in range(8799, 8830):
        with socket.socket() as s_:
            s_.settimeout(0.3)
            if s_.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return 8799


PUERTO = _puerto_libre()

# Consola en UTF-8 (tildes y eñes correctas en la ventana negra)
try:
    os.system("chcp 65001 >nul")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    os.remove(REPORT)
except OSError:
    pass


def out(msg=""):
    print(msg, flush=True)
    try:
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
    except OSError:
        pass


def paso(t):
    out("")
    out("=" * 64)
    out(t)
    out("=" * 64)


def check(etiqueta, fn):
    try:
        r = fn()
        out(f"[OK]    {etiqueta}" + (f": {r}" if r not in (None, "") else ""))
        return True
    except BaseException:
        out(f"[ERROR] {etiqueta}")
        out(traceback.format_exc())
        return False


def webview2():
    for hive, ruta in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]:
        try:
            with winreg.OpenKey(hive, ruta) as k:
                return winreg.QueryValueEx(k, "pv")[0]
        except OSError:
            continue
    raise RuntimeError("WebView2 no está instalado (la ventana de la app lo necesita). Descárgalo de https://go.microsoft.com/fwlink/p/?LinkId=2124703")


def modulos():
    ok = True
    for m in MODULOS:
        ok &= check(f"import {m}", lambda m=m: getattr(__import__(m), "__version__", "ok"))
    return ok


def main():
    paso("1. Entorno")
    out(f"Python {sys.version.split()[0]} · {sys.executable}")
    out(f"Carpeta de la app: {APP}")
    sys.path.insert(0, APP)
    os.chdir(APP)

    paso("2. Módulos de Python")
    if not modulos():
        paso("2b. Reparación")
        r = input("Faltan paquetes. ¿Reinstalarlos desde internet ahora? (S/N): ").strip().lower()
        if r.startswith("s"):
            py = os.path.join(ROOT, "runtime", "python.exe")
            p = subprocess.run([py, "-s", "-m", "pip", "install", "--no-warn-script-location", "-r",
                                os.path.join(APP, "requirements.txt")], capture_output=True, text=True)
            out(p.stdout[-1500:])
            if p.returncode:
                out("[ERROR] pip falló:\n" + p.stderr[-2000:])
            modulos()

    paso("3. WebView2")
    check("Microsoft Edge WebView2 Runtime", webview2)

    paso("4. Datos del usuario")
    check("carpeta de datos escribible", lambda: __import__("puente.config", fromlist=["DATA"]).DATA)

    paso("5. Servidor local")
    def servidor():
        import uvicorn
        from server import app
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PUERTO, log_level="warning"))
        threading.Thread(target=srv.run, daemon=True).start()
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/api/estado", timeout=2) as r:
                    return f"HTTP {r.status}"
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("el servidor no respondió")
    ok = check(f"servidor en el puerto {PUERTO}", servidor)

    paso("6. FreeLLMAPI (IA)")
    def fl():
        from puente import freellmapi, llm
        e = freellmapi.estado(llm.config_activa())
        if not e['corriendo']:
            raise RuntimeError('FreeLLMAPI no responde en ' + e['url'])
        return 'activo, clave ' + ('valida' if e['clave_valida'] else 'NO valida')
    check('FreeLLMAPI', fl)

    paso("7. Red: OpenAlex, LibGen, Anna's Archive, Sci-Hub y túnel")
    if ok:
        def red():
            import json
            req = urllib.request.Request(f"http://127.0.0.1:{PUERTO}/api/diagnostico", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read().decode("utf-8"))
            for x in d["resultados"]:
                out(f"   {'OK   ' if x['ok'] else 'FALLA'} {x['grupo']:<15} {x['nombre']:<34} {x['ruta']:<8} {x['detalle']}")
            for sug in d.get("sugerencias", []):
                out(f"   → {sug}")
            return "ver detalle arriba"
        check("diagnóstico de red", red)

    paso("8. Ventana nativa")
    if ok:
        def ventana():
            import webview
            webview.create_window("Puente Científico (diagnóstico)", f"http://127.0.0.1:{PUERTO}/", width=1200, height=800)
            out("Ventana abierta. Ciérrala para terminar.")
            webview.start(gui="edgechromium")
            return "cerrada por el usuario"
        check("abrir ventana", ventana)

    paso("Resultado")
    out(f"Informe guardado en: {REPORT}")
    out("Si algún paso dice [ERROR], comparte ese bloque completo.")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        out(traceback.format_exc())
    input("\nPresiona Enter para cerrar…")

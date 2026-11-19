"""DiagnÃ³stico de Puente CientÃ­fico: revisa paso a paso por quÃ© la app no abre.
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
MODULOS = ["fastapi", "uvicorn", "multipart", "webview", "clr_loader", "fitz", "requests", "socks", "lxml", "feedparser", "bs4", "pathvalidate"]
PUERTO = 8799

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
    raise RuntimeError("WebView2 no estÃ¡ instalado (la ventana de la app lo necesita). DescÃ¡rgalo de https://go.microsoft.com/fwlink/p/?LinkId=2124703")


def modulos():
    ok = True
    for m in MODULOS:
        ok &= check(f"import {m}", lambda m=m: getattr(__import__(m), "__version__", "ok"))
    return ok


def main():
    paso("1. Entorno")
    out(f"Python {sys.version.split()[0]} Â· {sys.executable}")
    out(f"Carpeta de la app: {APP}")
    sys.path.insert(0, APP)
    os.chdir(APP)

    paso("2. MÃ³dulos de Python")
    if not modulos():
        paso("2b. ReparaciÃ³n")
        r = input("Faltan paquetes. Â¿Reinstalarlos desde internet ahora? (S/N): ").strip().lower()
        if r.startswith("s"):
            py = os.path.join(ROOT, "runtime", "python.exe")
            p = subprocess.run([py, "-s", "-m", "pip", "install", "--no-warn-script-location", "-r",
                                os.path.join(APP, "requirements.txt")], capture_output=True, text=True)
            out(p.stdout[-1500:])
            if p.returncode:
                out("[ERROR] pip fallÃ³:\n" + p.stderr[-2000:])
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
        raise RuntimeError("el servidor no respondiÃ³")
    ok = check(f"servidor en el puerto {PUERTO}", servidor)

    paso("6. FreeLLMAPI (IA)")
    def fl():
        from puente import freellmapi, llm
        e = freellmapi.estado(llm.config_activa())
        if not e['corriendo']:
            raise RuntimeError('FreeLLMAPI no responde en ' + e['url'])
        return 'activo, clave ' + ('valida' if e['clave_valida'] else 'NO valida')
    check('FreeLLMAPI', fl)

    paso("7. Ventana nativa")
    if ok:
        def ventana():
            import webview
            webview.create_window("Puente CientÃ­fico (diagnÃ³stico)", f"http://127.0.0.1:{PUERTO}/", width=1200, height=800)
            out("Ventana abierta. CiÃ©rrala para terminar.")
            webview.start(gui="edgechromium")
            return "cerrada por el usuario"
        check("abrir ventana", ventana)

    paso("Resultado")
    out(f"Informe guardado en: {REPORT}")
    out("Si algÃºn paso dice [ERROR], comparte ese bloque completo.")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        out(traceback.format_exc())
    input("\nPresiona Enter para cerrarâ€¦")

"""Lanzador de Puente Científico: servidor local + ventana nativa de Windows (WebView2)."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

from puente import APP_NAME, __version__  # noqa: E402
from puente.config import LOG_PATH  # noqa: E402

PUERTO_BASE = 8777


def _log_a_archivo() -> None:
    # Con pythonw no hay consola: todo va a %APPDATA%\PuenteCientifico\servidor.log
    if sys.stdout is None or not sys.stdout.isatty():
        f = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
    print(f"\n==== {APP_NAME} {__version__} · {time.strftime('%Y-%m-%d %H:%M:%S')} ====")


def _respuesta(puerto: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/instancia", timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _libre(puerto: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def elegir_puerto() -> tuple[int, bool]:
    """Devuelve (puerto, ya_en_marcha). Si otra copia de ESTA instalación ya sirve, se reutiliza."""
    for puerto in range(PUERTO_BASE, PUERTO_BASE + 20):
        if _libre(puerto):
            return puerto, False
        info = _respuesta(puerto)
        if info and info.get("carpeta") == str(HERE):
            return puerto, True
    raise RuntimeError("No hay puertos libres entre 8777 y 8796.")


def iniciar_servidor(puerto: int) -> None:
    import uvicorn

    from server import app

    config = uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="servidor").start()
    for _ in range(200):
        if _respuesta(puerto):
            return
        time.sleep(0.1)
    raise RuntimeError("El servidor local no respondió a tiempo.")


def mensaje_error(texto: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, APP_NAME, 0x10)
    except Exception:
        pass


_MUTEX = None


def ya_abierta() -> bool:
    """Instancia única por instalación: un mutex con nombre de Windows (atómico, sin carreras)."""
    global _MUTEX
    try:
        import ctypes
        import hashlib
        nombre = "Local\\PuenteCientifico-" + hashlib.sha1(str(HERE).lower().encode()).hexdigest()[:16]
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, nombre)
        return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def activar_existente(navegador: bool) -> None:
    """Otra copia ya corre: se le pide que muestre su ventana (o se abre en el navegador) y esta termina."""
    for _ in range(60):  # la primera copia puede estar arrancando todavía
        for puerto in range(PUERTO_BASE, PUERTO_BASE + 20):
            info = _respuesta(puerto)
            if info and info.get("carpeta") == str(HERE):
                url = f"http://127.0.0.1:{puerto}/"
                try:
                    req = urllib.request.Request(url + "api/ventana/mostrar", data=b"{}", method="POST",
                                                 headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        ok = json.loads(r.read().decode("utf-8")).get("ok")
                except Exception:
                    ok = False
                if navegador or not ok:
                    webbrowser.open(url)
                print("Ya había una copia abierta: se activó su ventana.")
                return
        time.sleep(0.5)
    mensaje_error("Puente Científico ya se está abriendo. Espera unos segundos.")


def main() -> None:
    _log_a_archivo()
    try:  # la barra de tareas agrupa la ventana con el acceso directo (icono propio, no el de Python)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PuenteCientifico.App")
    except Exception:
        pass
    navegador = "--navegador" in sys.argv
    if ya_abierta():
        activar_existente(navegador)
        return
    puerto, en_marcha = elegir_puerto()
    url = f"http://127.0.0.1:{puerto}/"
    stop = threading.Event()
    if not en_marcha:
        iniciar_servidor(puerto)
        from puente import news
        threading.Thread(target=news.programador, args=(stop,), daemon=True, name="noticias").start()
    print("Sirviendo en", url)
    if navegador:
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    try:
        import webview

        import server
        ventana = webview.create_window(
            APP_NAME, url, width=1440, height=900, min_size=(1024, 680), maximized=True,
            background_color="#F2F0E9", text_select=True,
        )
        server.WINDOW["ventana"] = ventana
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=str(Path(LOG_PATH).parent / "webview"))
    except Exception:
        traceback.print_exc()
        mensaje_error("No se pudo abrir la ventana (¿falta Microsoft Edge WebView2?).\n"
                      "Se abrirá la aplicación en tu navegador.")
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    finally:
        stop.set()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        mensaje_error("Puente Científico no pudo iniciar:\n\n" + traceback.format_exc()[-800:])

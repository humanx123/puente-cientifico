"""Túnel de privacidad para la búsqueda y descarga de literatura.

Modos (Ajustes → Literatura → Túnel):
- "directo": conexión normal.
- "tor":     Tor integrado (Tor Expert Bundle, código abierto) como proxy SOCKS5 solo para esta app;
             no requiere administrador ni cambia la red de Windows. Resuelve los nombres dentro del
             túnel (socks5h), lo que evita bloqueos por DNS o por dominio. Admite puentes Snowflake
             y obfs4 (lyrebird) para redes que bloquean Tor.
- "proxy":   el proxy HTTP/SOCKS5 de tu VPN (Mysterium, Proton, WireGuard con proxy, etc.).

Solo pasa por el túnel el tráfico de literatura (OpenAlex, acceso abierto, Sci-Hub, LibGen,
Anna's Archive). La IA y las noticias usan la conexión normal.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from .config import BASE_DIR, DATA, load_settings

TOR_DATA = DATA / "tor"
_estado = {"estado": "apagado", "progreso": 0, "mensaje": "", "puerto": None, "inicio": None}
_proc: subprocess.Popen | None = None
_lock = threading.Lock()
log = logging.getLogger("tor")


def carpeta_tor() -> Path | None:
    for c in (BASE_DIR.parent / "tor",                          # instalado: {app}\tor
              BASE_DIR.parent / "build" / "cache" / "tor"):     # desarrollo
        if (c / "tor" / "tor.exe").exists():
            return c
    return None


def disponible() -> bool:
    return carpeta_tor() is not None


def _puerto_libre(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", p)) != 0


def _puentes(tipo: str, propios: str) -> tuple[list[str], str]:
    """Devuelve (líneas Bridge, línea ClientTransportPlugin) para snowflake/obfs4/propios."""
    base = carpeta_tor()
    pt_dir = base / "tor" / "pluggable_transports"
    lyre = str(pt_dir / "lyrebird.exe")
    plugin = f"ClientTransportPlugin meek_lite,obfs4,webtunnel,snowflake exec {lyre}"
    if tipo == "propios":
        lineas = [l.strip() for l in (propios or "").splitlines() if l.strip() and not l.strip().startswith("#")]
        lineas = [re.sub(r"^Bridge\s+", "", l, flags=re.I) for l in lineas]
        return lineas, plugin
    try:
        cfg = json.loads((pt_dir / "pt_config.json").read_text(encoding="utf-8"))
        return list(cfg["bridges"].get(tipo, [])), plugin
    except (OSError, ValueError, KeyError):
        return [], plugin


def _torrc(puerto: int) -> Path:
    s = load_settings()["literatura"]
    base = carpeta_tor()
    TOR_DATA.mkdir(parents=True, exist_ok=True)
    lineas = [
        f"SocksPort 127.0.0.1:{puerto}",
        f"DataDirectory {_carpeta_datos_libre()}",
        f"GeoIPFile {base / 'data' / 'geoip'}",
        f"GeoIPv6File {base / 'data' / 'geoip6'}",
        "AvoidDiskWrites 1",
        "Log notice stdout",
        "ClientOnly 1",
    ]
    tipo = s.get("tor_puentes", "ninguno")
    if tipo in ("snowflake", "obfs4", "propios"):
        bridges, plugin = _puentes(tipo, s.get("tor_puentes_propios", ""))
        if bridges:
            lineas += ["UseBridges 1", plugin] + [f"Bridge {b}" for b in bridges]
    if s.get("tor_salida"):  # país de salida, p. ej. {de},{nl}
        paises = ",".join("{" + c.strip().lower() + "}" for c in s["tor_salida"].split(",") if re.fullmatch(r"[A-Za-z]{2}", c.strip()))
        if paises:
            lineas += [f"ExitNodes {paises}", "StrictNodes 0"]
    ruta = TOR_DATA / "torrc"
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


ERRORES_TOR = [
    (r"\bclock\b|skew", "La hora de Windows no es correcta: Tor la necesita exacta. Sincroniza el reloj."),
    (r"another tor process|is tor already running|\block\b", "Otra copia de Tor usaba la misma carpeta de datos (se cerró y se reintenta)."),
    (r"could not bind|address already in use|10048", "El puerto del túnel estaba ocupado (se usará otro)."),
    (r"no route|network is unreachable|connection refused|timed out", "La red no deja conectar con Tor. Prueba los puentes Snowflake."),
]
_huerfanos_cerrados = []


def _cerrar_huerfanos() -> int:
    """Cierra tor.exe de ESTA app que quedaron de una sesión anterior (nunca un Tor Browser del usuario)."""
    base = carpeta_tor()
    if not base or os.name != "nt":
        return 0
    exe = str(base / "tor" / "tor.exe")
    # En PowerShell, una cadena entre comillas simples no interpreta barras invertidas: solo se escapan las comillas.
    ruta_ps = exe.replace("'", "''")
    # También cualquier tor.exe que use NUESTRA carpeta de datos (p. ej. de otra instalación de la app en
    # otra carpeta): con el mutex de instancia única, ese proceso es necesariamente un huérfano y bloquea
    # el DataDirectory («Reading config failed»).
    datos_ps = str(TOR_DATA).replace("'", "''")
    cmd = (f'$n=0; Get-CimInstance Win32_Process -Filter "Name=\'tor.exe\'" | Where-Object {{ $_.ExecutablePath -eq \'{ruta_ps}\''
           f' -or ($_.CommandLine -and $_.CommandLine.Contains(\'{datos_ps}\')) }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId'
           f' -Force -ErrorAction SilentlyContinue; $n++ }}; $n')
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=20,
                           creationflags=0x08000000)
        n = int((r.stdout or "0").strip().splitlines()[-1] or 0)
    except (subprocess.SubprocessError, ValueError, IndexError, OSError):
        n = 0
    if n:
        _huerfanos_cerrados.append(n)
        time.sleep(1.5)
    # Esperar a que se libere el bloqueo de la carpeta de datos.
    cerrojo = TOR_DATA / "datos" / "lock"
    for _ in range(20):
        try:
            if not cerrojo.exists():
                break
            cerrojo.unlink()
            break
        except OSError:
            time.sleep(0.5)
    return n


def _carpeta_datos_libre() -> Path:
    """Carpeta de datos usable; si la principal sigue bloqueada por otro proceso, una alternativa."""
    principal = TOR_DATA / "datos"
    cerrojo = principal / "lock"
    try:
        if cerrojo.exists():
            cerrojo.unlink()
        return principal
    except OSError:
        alt = TOR_DATA / f"datos-{os.getpid()}"
        alt.mkdir(parents=True, exist_ok=True)
        log.warning("La carpeta de datos de Tor sigue bloqueada; se usa %s", alt)
        return alt


def _leer_salida(proc: subprocess.Popen) -> None:
    for linea in iter(proc.stdout.readline, ""):
        m = re.search(r"Bootstrapped (\d+)%[^:]*: (.*)", linea)
        if m:
            _estado["progreso"] = int(m.group(1))
            _estado["mensaje"] = m.group(2).strip()[:120]
            if _estado["progreso"] >= 100:
                _estado["estado"] = "listo"
        elif "[err]" in linea or "[warn]" in linea:
            texto = linea.split("]", 1)[-1].strip()
            log.warning("tor: %s", texto[:300])
            _estado.setdefault("registro", []).append(texto[:200])
            amable = next((msg for patron, msg in ERRORES_TOR if re.search(patron, texto, re.I)), None)
            if amable:
                _estado["mensaje"] = amable
                _estado["amable"] = True
            elif "[err]" in linea or "bridge" in linea.lower():
                generico = re.search(r"reading config failed|see warnings above", texto, re.I)
                if generico and _estado.get("amable"):
                    continue  # no tapar la causa real ya explicada
                if generico:
                    previos = [r for r in _estado["registro"][:-1] if not re.search(r"see warnings above", r, re.I)]
                    _estado["mensaje"] = (previos[-1] if previos else texto)[:160]
                else:
                    _estado["mensaje"] = texto[:160]
    if _estado["estado"] != "apagado":
        _estado["estado"] = "error"
        _estado["mensaje"] = _estado["mensaje"] or "Tor se detuvo."


def iniciar() -> dict:
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            return estado()
        base = carpeta_tor()
        if not base:
            raise RuntimeError("Tor no está incluido en esta instalación.")
        _cerrar_huerfanos()
        _estado["registro"] = []
        _estado["amable"] = False
        puerto = int(load_settings()["literatura"].get("tor_puerto", 9077))
        while not _puerto_libre(puerto) and puerto < 9100:
            puerto += 1
        torrc = _torrc(puerto)
        _estado.update(estado="iniciando", progreso=0, mensaje="Conectando con la red Tor…", puerto=puerto, inicio=time.time())
        _proc = subprocess.Popen(
            [str(base / "tor" / "tor.exe"), "-f", str(torrc), "--defaults-torrc", os.devnull if os.name != "nt" else "NUL"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", creationflags=0x08000000 if os.name == "nt" else 0,
        )
        threading.Thread(target=_leer_salida, args=(_proc,), daemon=True, name="tor-log").start()
    return estado()


def detener() -> dict:
    global _proc
    with _lock:
        _estado.update(estado="apagado", progreso=0, mensaje="", puerto=None)
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
        _proc = None
    return estado()


atexit.register(detener)


def estado() -> dict:
    vivo = _proc is not None and _proc.poll() is None
    if _estado["estado"] in ("listo", "iniciando") and not vivo:
        _estado.update(estado="error", mensaje=_estado.get("mensaje") or "El proceso de Tor terminó inesperadamente.")
    s = load_settings()["literatura"]
    return dict(_estado, disponible=disponible(), modo=s.get("tunel", "directo"), alcance=s.get("tunel_alcance", "bloqueados"),
                proceso_vivo=vivo)


def comprobar() -> dict:
    """¿El tráfico sale realmente por Tor? (check.torproject.org)"""
    import requests
    if _estado["estado"] != "listo":
        return {"ok": False, "detalle": f"Tor no está listo ({_estado['estado']} {_estado['progreso']}%)"}
    url = f"socks5h://127.0.0.1:{_estado['puerto']}"
    try:
        r = requests.get("https://check.torproject.org/api/ip", proxies={"http": url, "https": url}, timeout=40)
        d = r.json()
        return {"ok": bool(d.get("IsTor")), "detalle": f"IP de salida {d.get('IP')}" + (" (Tor confirmado)" if d.get("IsTor") else "")}
    except Exception as e:
        return {"ok": False, "detalle": f"sin respuesta a través de Tor ({type(e).__name__})"}


def esperar_listo(segundos: int = 90) -> None:
    if _estado["estado"] in ("apagado", "error"):
        iniciar()
    fin = time.time() + segundos
    while time.time() < fin:
        if _estado["estado"] == "listo":
            return
        if _estado["estado"] == "error":
            raise RuntimeError("Tor no pudo conectar: " + (_estado["mensaje"] or "error desconocido")
                               + ". Prueba los puentes Snowflake en Ajustes → Literatura.")
        time.sleep(0.5)
    raise RuntimeError(f"Tor sigue conectando ({_estado['progreso']}%). Vuelve a intentarlo en un momento.")


def proxies() -> dict | None:
    """Proxies para requests según el modo de túnel; None = conexión directa."""
    s = load_settings()["literatura"]
    modo = s.get("tunel", "directo")
    if modo == "tor":
        esperar_listo()
        url = f"socks5h://127.0.0.1:{_estado['puerto']}"
        return {"http": url, "https": url}
    if modo == "proxy" or s.get("proxy_activo"):
        from urllib.parse import quote
        auth = ""
        if s.get("proxy_usuario"):
            auth = quote(s["proxy_usuario"]) + ":" + quote(s.get("proxy_clave", "")) + "@"
        esquema = "socks5h" if s.get("proxy_tipo") == "socks5" else "http"
        url = f"{esquema}://{auth}{s['proxy_host']}:{s['proxy_puerto']}"
        return {"http": url, "https": url}
    return None

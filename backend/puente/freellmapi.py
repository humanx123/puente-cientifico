"""Integración con FreeLLMAPI (https://github.com/tashfeenahmed/freellmapi).

Proxy autoalojado compatible con OpenAI que reúne las capas gratuitas de ~14 proveedores
(Gemini, Groq, Cerebras, SambaNova, NVIDIA, Mistral, OpenRouter, GitHub Models…) con
conmutación automática ante 429/5xx. La app lo usa con model="auto".

Este módulo detecta una instalación local, importa la clave unificada desde su base de
datos (solo lectura, a petición del usuario) y puede arrancar el servidor si está apagado.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

import requests

RUTAS_PROBABLES = [
    Path.home() / "freellmapi",
    Path.home() / "Projects" / "freellmapi",
    Path.home() / "Apps" / "freellmapi",
    Path.home() / "Documents" / "freellmapi",
]


def _ruta(ruta: str | None) -> Path | None:
    candidatas = [Path(ruta)] if ruta else []
    candidatas += RUTAS_PROBABLES
    for c in candidatas:
        if (c / "server" / "dist" / "index.js").exists() or (c / "server" / "data" / "freeapi.db").exists():
            return c
    return None


def _db(carpeta: Path) -> Path:
    env = os.environ.get("FREEAPI_DB_PATH")
    return Path(env) if env else carpeta / "server" / "data" / "freeapi.db"


def responde(url: str, clave: str = "", timeout: float = 3) -> tuple[bool, int | None]:
    """(servidor vivo, código HTTP de /models). 401 = vivo pero falta o falla la clave."""
    try:
        h = {"Authorization": f"Bearer {clave}"} if clave else {}
        r = requests.get(url.rstrip("/") + "/models", headers=h, timeout=timeout,
                         proxies={"http": None, "https": None})
        return True, r.status_code
    except requests.RequestException:
        return False, None


def leer_clave(ruta: str | None = None) -> str:
    carpeta = _ruta(ruta)
    if not carpeta:
        raise ValueError("No encontré una instalación de FreeLLMAPI. Indica su carpeta en Ajustes.")
    db = _db(carpeta)
    if not db.exists():
        raise ValueError(f"No existe la base de datos de FreeLLMAPI en {db}. Arráncalo una vez para crearla.")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        fila = con.execute("SELECT value FROM settings WHERE key='unified_api_key'").fetchone()
    finally:
        con.close()
    if not fila or not str(fila[0]).startswith("freellmapi-"):
        raise ValueError("La base de FreeLLMAPI no tiene clave unificada todavía. Ábrela desde su panel (Keys).")
    return str(fila[0])


def arrancar(ruta: str | None, url: str, espera: float = 20) -> bool:
    carpeta = _ruta(ruta)
    if not carpeta or not (carpeta / "server" / "dist" / "index.js").exists():
        return False
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    log = open(carpeta / "server" / "data" / "puente-arranque.log", "a", encoding="utf-8") if (carpeta / "server" / "data").exists() else subprocess.DEVNULL
    try:
        subprocess.Popen(["node", "server/dist/index.js"], cwd=str(carpeta), stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags)
    except (OSError, FileNotFoundError):
        return False
    fin = time.time() + espera
    while time.time() < fin:
        if responde(url, timeout=1.5)[0]:
            return True
        time.sleep(0.7)
    return False


def estado(cfg: dict) -> dict:
    carpeta = _ruta(cfg.get("freellmapi_ruta"))
    vivo, codigo = responde(cfg["freellmapi_url"], cfg.get("freellmapi_clave", ""))
    return {
        "instalado": bool(carpeta),
        "carpeta": str(carpeta) if carpeta else "",
        "corriendo": vivo,
        "clave_valida": codigo == 200,
        "codigo": codigo,
        "url": cfg["freellmapi_url"],
        "panel": cfg["freellmapi_url"].rstrip("/").removesuffix("/v1"),
    }

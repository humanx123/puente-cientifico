"""Rutas de datos del usuario y ajustes persistentes (JSON en %APPDATA%)."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

from . import APP_ID

BASE_DIR = Path(__file__).resolve().parent.parent  # carpeta backend/ o app/


def data_root() -> Path:
    override = os.environ.get("PUENTE_DATA_DIR")
    if override:
        root = Path(override)
    else:
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA = data_root()
LIBRARY_DIR = DATA / "biblioteca"
TRANSLATED_DIR = DATA / "traducciones"
CACHE_DIR = DATA / "cache"
EXPORT_DIR = DATA / "exportaciones"
for _d in (LIBRARY_DIR, TRANSLATED_DIR, CACHE_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA / "puente.sqlite3"
SETTINGS_PATH = DATA / "ajustes.json"
LOG_PATH = DATA / "servidor.log"

DEFAULT_SETTINGS = {
    "traduccion": {
        "proveedor": "freellmapi",  # freellmapi | openai | ollama
        "freellmapi_url": "http://127.0.0.1:3001/v1",
        "freellmapi_clave": "",
        "freellmapi_modelo": "auto",
        "freellmapi_ruta": "",  # carpeta de la instalación local (vacío = detectar)
        "freellmapi_autoarranque": True,
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_modelo": "",
        "openai_url": "https://api.openai.com/v1",
        "openai_clave": "",
        "openai_modelo": "gpt-4o-mini",
        "idioma_origen": "en",
        "idioma_destino": "es",
        "temperatura": 0.2,
        "glosarios_activos": [],
        "proxy_modo": "sistema",  # sistema | directo | manual
        "proxy_url": "",
    },
    "asistente": {
        "proveedor": "",  # vacío = el mismo que traducción
        "modelo": "",
    },
    "literatura": {
        "fuente": "auto",  # auto | abierto | scihub
        "scihub_url": "https://sci-hub.ru",
        "scihub_espejos": ["https://sci-hub.ru", "https://sci-hub.se", "https://sci-hub.st", "https://sci-hub.su"],
        "xpaths_pdf": [
            '//div[@id="article"]/embed[1]',
            '//div[@id="article"]/iframe[1]',
            '//embed[@id="pdf"]',
            '//iframe[@id="pdf"]',
            '//object[@type="application/pdf"]',
        ],
        "xpath_captcha_id": ['//input[@name="id"]'],
        "xpath_captcha_img": ['//img[@id="captcha"]'],
        "formato_nombre": "{id}_{year}_{author}_{title}",
        "sobrescribir": False,
        "tiempo_espera_ms": 15000,
        "reintentos": 3,
        "agente_usuario": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        ),
        "proxy_activo": False,
        "proxy_tipo": "http",  # http | socks5
        "proxy_host": "127.0.0.1",
        "proxy_puerto": "7890",
        "proxy_usuario": "",
        "proxy_clave": "",
        "openalex_correo": "",
        "openalex_clave": "",
        "guardar_copia_en": "",  # carpeta extra donde dejar el PDF además de la biblioteca
    },
    "noticias": {
        "intervalo_horas": 3,
        "max_elementos": 600,
    },
    "apariencia": {
        "tema": "claro",  # claro | oscuro
        "acento": "#ff3d00",
        "zoom": 1.0,
    },
}

_lock = threading.Lock()
SECRETOS = (("traduccion", "openai_clave"), ("traduccion", "freellmapi_clave"),
            ("literatura", "openalex_clave"), ("literatura", "proxy_clave"))


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    with _lock:
        if SETTINGS_PATH.exists():
            try:
                stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                stored = {}
        else:
            stored = {}
        return _merge(DEFAULT_SETTINGS, stored)


def save_settings(patch: dict) -> dict:
    current = load_settings()
    merged = _merge(current, patch or {})
    with _lock:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_PATH)
    return merged


def public_settings() -> dict:
    """Ajustes para la interfaz: las claves se ocultan (solo se indica si existen)."""
    s = load_settings()
    s = copy.deepcopy(s)
    for section, key in SECRETOS:
        s[section][key + "_configurada"] = bool(s[section].get(key))
        s[section][key] = ""
    return s

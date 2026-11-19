"""Cliente de modelos de lenguaje.

Proveedores:
- freellmapi (por defecto): proxy FreeLLMAPI con model="auto"; conmuta solo entre ~14 capas gratuitas.
- openai: cualquier API compatible con OpenAI (OpenAI, Groq, OpenRouter, DeepSeek, NVIDIA, LM Studio…).
- ollama: modelos locales.
"""
from __future__ import annotations

import threading
import time

import requests

from .config import load_settings


class LLMError(Exception):
    """fatal=True: no tiene sentido seguir (sin conexión, sin modelo, clave rechazada)."""

    def __init__(self, msg: str, fatal: bool = False):
        super().__init__(msg)
        self.fatal = fatal


ULTIMA_RUTA = {"via": ""}  # proveedor/modelo real que respondió (cabecera X-Routed-Via)
_arranque_lock = threading.Lock()


def _session(cfg: dict) -> requests.Session:
    s = requests.Session()
    modo = cfg.get("proxy_modo", "sistema")
    base = _base(cfg)
    local = "127.0.0.1" in base or "localhost" in base  # lo local nunca pasa por proxy
    if modo == "directo" or local:
        s.trust_env = False
        s.proxies = {}
    elif modo == "manual" and cfg.get("proxy_url"):
        s.trust_env = False
        s.proxies = {"http": cfg["proxy_url"], "https": cfg["proxy_url"]}
    return s


def config_activa(para: str = "traduccion") -> dict:
    s = load_settings()
    cfg = dict(s["traduccion"])
    if para == "asistente":
        a = s.get("asistente", {})
        if a.get("proveedor"):
            cfg["proveedor"] = a["proveedor"]
        if a.get("modelo"):
            cfg[_campo_modelo(cfg)] = a["modelo"]
    return cfg


def _campo_modelo(cfg: dict) -> str:
    return {"ollama": "ollama_modelo", "freellmapi": "freellmapi_modelo"}.get(cfg["proveedor"], "openai_modelo")


def _base(cfg: dict) -> str:
    if cfg["proveedor"] == "freellmapi":
        return cfg.get("freellmapi_url", "http://127.0.0.1:3001/v1").rstrip("/")
    if cfg["proveedor"] == "ollama":
        return cfg.get("ollama_url", "").rstrip("/")
    return cfg.get("openai_url", "").rstrip("/")


def _clave(cfg: dict) -> str:
    return cfg.get("freellmapi_clave", "") if cfg["proveedor"] == "freellmapi" else cfg.get("openai_clave", "")


def modelo_de(cfg: dict) -> str:
    return cfg.get(_campo_modelo(cfg)) or ("auto" if cfg["proveedor"] == "freellmapi" else "")


def _asegurar_freellmapi(cfg: dict) -> None:
    """Si FreeLLMAPI local está apagado y el autoarranque está activo, lo inicia."""
    from . import freellmapi
    url = _base(cfg)
    if freellmapi.responde(url, timeout=1.5)[0]:
        return
    if not cfg.get("freellmapi_autoarranque", True) or not ("127.0.0.1" in url or "localhost" in url):
        raise LLMError(f"FreeLLMAPI no responde en {url}. Arráncalo o revisa la dirección en Ajustes.", fatal=True)
    with _arranque_lock:
        if freellmapi.responde(url, timeout=1.5)[0]:
            return
        if not freellmapi.arrancar(cfg.get("freellmapi_ruta"), url):
            raise LLMError("FreeLLMAPI no está corriendo y no pude iniciarlo. Revisa su carpeta en Ajustes "
                           "o arráncalo con: node server/dist/index.js", fatal=True)


def listar_modelos(cfg: dict | None = None) -> list[str]:
    cfg = cfg or config_activa()
    sess = _session(cfg)
    try:
        if cfg["proveedor"] == "ollama":
            r = sess.get(_base(cfg) + "/api/tags", timeout=8)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        if cfg["proveedor"] == "freellmapi":
            _asegurar_freellmapi(cfg)
        headers = {"Authorization": f"Bearer {_clave(cfg)}"} if _clave(cfg) else {}
        r = sess.get(_base(cfg) + "/models", headers=headers, timeout=15)
        if r.status_code == 401:
            raise LLMError("Clave rechazada (401). En FreeLLMAPI usa la clave unificada «freellmapi-…» del panel Keys.", fatal=True)
        r.raise_for_status()
        ids = sorted({m.get("id", "") for m in r.json().get("data", []) if m.get("id")})
        if cfg["proveedor"] == "freellmapi" and "auto" not in ids:
            ids.insert(0, "auto")
        return ids
    except requests.RequestException as e:
        if cfg["proveedor"] == "ollama":
            raise LLMError("No se pudo conectar con Ollama. ¿Está instalado y abierto? (" + str(e)[:120] + ")") from None
        raise LLMError("No se pudo listar modelos del proveedor: " + str(e)[:200]) from None


def _ollama(cfg, sess, modelo, messages, temp, json_mode, timeout, max_tokens) -> str:
    body = {"model": modelo, "messages": messages, "stream": False, "options": {"temperature": temp, "num_ctx": 8192}}
    if max_tokens:  # evita que un bucle de repetición del modelo dure minutos
        body["options"]["num_predict"] = int(max_tokens)
    if json_mode:
        body["format"] = "json"
    r = sess.post(_base(cfg) + "/api/chat", json=body, timeout=timeout)
    if r.status_code == 404:
        raise LLMError(f"Ollama no tiene el modelo «{modelo}». Descárgalo con: ollama pull {modelo}", fatal=True)
    if r.status_code != 200:
        raise LLMError(f"Ollama respondió HTTP {r.status_code}: {r.text[:200]}")
    return r.json().get("message", {}).get("content", "")


def _compatible_openai(cfg, sess, modelo, messages, temp, json_mode, timeout, max_tokens) -> str:
    es_fl = cfg["proveedor"] == "freellmapi"
    if not _clave(cfg) and (es_fl or "api.openai.com" in _base(cfg)):
        msg = ("Falta la clave unificada de FreeLLMAPI. Pulsa «Importar clave» en Ajustes → Traducción e IA."
               if es_fl else "Falta la clave de API en Ajustes → Traducción e IA.")
        raise LLMError(msg, fatal=True)
    headers = {"Authorization": f"Bearer {_clave(cfg)}", "Content-Type": "application/json"}
    body = {"model": modelo, "messages": messages, "temperature": temp}
    # Con FreeLLMAPI no se fuerza response_format ni max_tokens: varios proveedores gratuitos
    # rechazan el modo JSON estricto (Groq 400) y los modelos de razonamiento gastan tokens
    # pensando, lo que trunca la salida. El prompt ya exige JSON y el parser es tolerante.
    if not es_fl:
        if max_tokens:
            body["max_tokens"] = int(max_tokens) * 2
        if json_mode:
            body["response_format"] = {"type": "json_object"}
    url = _base(cfg) + "/chat/completions"
    # FreeLLMAPI devuelve 429/503 cuando todas las claves gratuitas están en enfriamiento: esperar y reintentar
    esperas = [0, 8, 20, 45] if es_fl else [0, 5]
    r = None
    for i, espera in enumerate(esperas):
        if espera:
            time.sleep(espera)
        r = sess.post(url, json=body, headers=headers, timeout=timeout)
        if r.status_code == 400 and json_mode and "response_format" in body:
            body.pop("response_format", None)
            r = sess.post(url, json=body, headers=headers, timeout=timeout)
        if r.status_code not in (429, 502, 503, 504):
            break
    if r.status_code in (401, 403):
        raise LLMError(f"La clave fue rechazada (HTTP {r.status_code})." +
                       (" Importa de nuevo la clave unificada de FreeLLMAPI." if es_fl else ""), fatal=True)
    if r.status_code == 404:
        raise LLMError("El proveedor no encontró ese modelo o la URL base es incorrecta (HTTP 404).", fatal=True)
    if r.status_code == 429:
        raise LLMError("Límite de uso alcanzado en todos los proveedores (HTTP 429). Espera unos minutos o añade claves en FreeLLMAPI."
                       if es_fl else "Límite de uso del proveedor alcanzado (HTTP 429). Espera un momento.")
    if r.status_code != 200:
        raise LLMError(f"El proveedor respondió HTTP {r.status_code}: {r.text[:200]}")
    ULTIMA_RUTA["via"] = r.headers.get("x-routed-via", "")
    data = r.json()
    return data["choices"][0]["message"].get("content") or ""


def chat(messages: list[dict], cfg: dict | None = None, *, temperatura: float | None = None,
         json_mode: bool = False, timeout: int = 240, max_tokens: int | None = None) -> str:
    cfg = cfg or config_activa()
    modelo = modelo_de(cfg)
    if not modelo:
        raise LLMError("Elige un modelo en Ajustes → Traducción e IA.", fatal=True)
    temp = cfg.get("temperatura", 0.2) if temperatura is None else temperatura
    if cfg["proveedor"] == "freellmapi":
        _asegurar_freellmapi(cfg)
    sess = _session(cfg)
    try:
        fn = _ollama if cfg["proveedor"] == "ollama" else _compatible_openai
        return fn(cfg, sess, modelo, messages, temp, json_mode, timeout, max_tokens)
    except requests.Timeout:
        raise LLMError("El modelo tardó demasiado en responder.") from None
    except requests.ConnectionError as e:
        quien = {"ollama": "Ollama (¿está abierto?)", "freellmapi": "FreeLLMAPI"}.get(cfg["proveedor"], "el proveedor de IA")
        raise LLMError(f"No se pudo conectar con {quien}: " + str(e)[:160], fatal=True) from None
    except requests.RequestException as e:
        raise LLMError("Error de conexión con el modelo: " + str(e)[:200]) from None

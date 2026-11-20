"""Ventana de verificación integrada (WebView2 = Edge real).

Algunas editoriales (Taylor & Francis, Wiley, Elsevier…) y espejos de Sci-Hub responden 403 o
«Just a moment…» a cualquier programa, aunque el artículo sea de acceso abierto. Un navegador real
supera esas comprobaciones (a veces solas, a veces con un clic del usuario). Esta ventana:
1. abre la página del artículo;
2. espera a que desaparezca la verificación;
3. localiza el PDF (enlace dado, meta citation_pdf_url, embed/iframe, enlaces «PDF»);
4. lo pide desde la propia página con fetch() y las cookies de esa sesión, y lo devuelve.
Si no logra capturarlo, deja la ventana abierta para que el usuario lo descargue: la app vigila la
carpeta Descargas y lo importa en cuanto aparece.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

RETO = ("just a moment", "un momento", "attention required", "verify you are human", "checking your browser",
        "ddos-guard", "captcha", "altcha", "verificación")

_JS_BUSCAR_PDF = r"""
(() => {
  const abs = (u) => { try { return new URL(u, location.href).href } catch (e) { return null } };
  const c = [];
  const m = document.querySelector('meta[name="citation_pdf_url"]'); if (m) c.push(abs(m.content));
  document.querySelectorAll('embed[src],iframe[src],object[data]').forEach(e => {
    const u = e.getAttribute('src') || e.getAttribute('data'); if (u && /pdf/i.test(u + (e.type || ''))) c.push(abs(u)); });
  document.querySelectorAll('a[href]').forEach(a => {
    const t = (a.textContent || '').trim().toLowerCase(), h = a.getAttribute('href') || '';
    if (/\.pdf(\?|#|$)|\/pdf\/|\/epdf\/|pdfdirect|download/i.test(h) || t === 'pdf' || t.includes('download pdf') || t.includes('descargar pdf')) c.push(abs(h)); });
  if (document.contentType === 'application/pdf') c.unshift(location.href);
  return JSON.stringify([...new Set(c.filter(Boolean))].slice(0, 12));
})()
"""

_JS_FETCH = r"""
(() => {
  window.__pc = null; window.__pcInfo = null;
  fetch(%s, {credentials: 'include'}).then(r => { window.__pcInfo = (r.headers.get('content-type') || '') + '|' + r.status; return r.arrayBuffer() })
    .then(b => { const u = new Uint8Array(b); let s = ''; for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); window.__pc = btoa(s) })
    .catch(e => { window.__pc = 'ERR:' + e });
  return 1;
})()
"""


def disponible() -> bool:
    try:
        import server
        return server.WINDOW.get("ventana") is not None
    except Exception:
        return False


def _js(ventana, codigo: str, defecto=None):
    try:
        return ventana.evaluate_js(codigo)
    except Exception:
        return defecto


def _bajar_en_pagina(ventana, url: str, espera: int = 90) -> bytes | None:
    _js(ventana, _JS_FETCH % json.dumps(url))
    fin = time.time() + espera
    while time.time() < fin:
        estado = _js(ventana, "window.__pc === null ? 0 : (String(window.__pc).startsWith('ERR:') ? -1 : window.__pc.length)", 0)
        if estado == -1:
            return None
        if estado and estado > 0:
            partes, trozo = [], 2_000_000
            for i in range(0, int(estado), trozo):
                partes.append(_js(ventana, f"window.__pc.slice({i}, {i + trozo})", "") or "")
            datos = base64.b64decode("".join(partes))
            _js(ventana, "window.__pc = null")
            return datos if datos[:1024].find(b"%PDF-") >= 0 else None
        time.sleep(0.6)
    return None


def capturar(pagina: str, pdf: str | None = None, titulo: str = "Verificación", log=None, espera_reto: int = 180) -> bytes | None:
    """Abre la ventana integrada y devuelve los bytes del PDF, o None si no se pudo capturar."""
    import webview
    log = log or (lambda *_: None)
    ventana = webview.create_window(f"Puente Científico · {titulo[:60]}", pagina, width=1100, height=820)
    try:
        for _ in range(60):  # esperar a que la ventana exista y cargue
            if _js(ventana, "document.readyState") in ("interactive", "complete"):
                break
            time.sleep(0.5)
        fin = time.time() + espera_reto
        avisado = False
        while time.time() < fin:
            t = (_js(ventana, "(document.title + ' ' + (document.body ? document.body.innerText.slice(0, 600) : '')).toLowerCase()", "") or "")
            if not any(r in t for r in RETO) and _js(ventana, "document.readyState") == "complete":
                break
            if not avisado:
                log("La página pide verificación: complétala en la ventana que se abrió (suele resolverse sola en segundos).", "aviso")
                avisado = True
            time.sleep(1.5)
        else:
            log("La verificación no se completó a tiempo.", "aviso")
            return None
        log("Verificación superada. Buscando el PDF en la página…")
        candidatos = ([pdf] if pdf else []) + json.loads(_js(ventana, _JS_BUSCAR_PDF, "[]") or "[]")
        for url in dict.fromkeys(c for c in candidatos if c):
            datos = _bajar_en_pagina(ventana, url)
            if datos:
                log(f"PDF capturado desde la página ({len(datos) / 1048576:.1f} MB).", "ok")
                return datos
        return None
    finally:
        try:
            ventana.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sesión de navegador persistente por sitio (DDoS-Guard / Cloudflare de Anna's Archive, Sci-Hub…)
# ---------------------------------------------------------------------------
_sesiones: dict[str, object] = {}
_JS_TEXTO = r"""
(() => {
  window.__pcTxt = null;
  fetch(%s, {credentials: 'include'}).then(r => r.text().then(t => { window.__pcTxt = JSON.stringify({s: r.status, t: t}) }))
    .catch(e => { window.__pcTxt = JSON.stringify({s: 0, t: 'ERR:' + e}) });
  return 1;
})()
"""


def _reto_activo(ventana) -> bool:
    t = (_js(ventana, "(document.title + ' ' + (document.body ? document.body.innerText.slice(0, 600) : '')).toLowerCase()", "") or "")
    return any(r in t for r in RETO) or _js(ventana, "document.readyState") != "complete"


def _sesion_para(base: str, log=None, espera: int = 120):
    """Ventana Edge que supera el reto del sitio una vez y luego se oculta; se reutiliza en la sesión."""
    import webview
    log = log or (lambda *_: None)
    v = _sesiones.get(base)
    if v is not None and _js(v, "1") == 1:
        return v
    v = webview.create_window(f"Puente Científico · verificando {base.split('//')[-1]}", base + "/", width=760, height=560)
    for _ in range(60):
        if _js(v, "document.readyState") in ("interactive", "complete"):
            break
        time.sleep(0.5)
    fin, avisado = time.time() + espera, False
    while time.time() < fin and _reto_activo(v):
        if not avisado:
            log(f"{base.split('//')[-1]} pide verificación anti-robots: se resuelve en la ventana pequeña (normalmente sola).", "aviso")
            avisado = True
        time.sleep(1.5)
    if _reto_activo(v):
        try:
            v.destroy()
        except Exception:
            pass
        return None
    try:
        v.hide()
    except Exception:
        pass
    _sesiones[base] = v
    return v


def obtener_texto(base: str, url: str, log=None, espera: int = 60) -> tuple[int, str] | None:
    """GET de `url` desde dentro de la sesión verificada de `base` (mismo origen, con sus cookies)."""
    v = _sesion_para(base, log)
    if v is None:
        return None
    _js(v, _JS_TEXTO % json.dumps(url))
    fin = time.time() + espera
    while time.time() < fin:
        r = _js(v, "window.__pcTxt")
        if r:
            d = json.loads(r)
            if str(d.get("t", "")).startswith("ERR:"):
                _sesiones.pop(base, None)
                return None
            if d.get("s") in (403, 503) and any(x in d.get("t", "")[:4000].lower() for x in RETO):
                _sesiones.pop(base, None)  # la verificación caducó: se rehará la próxima vez
                return None
            return int(d.get("s") or 0), d.get("t", "")
        time.sleep(0.4)
    return None


def vigilar_descargas(desde: float, segundos: int = 600) -> Path | None:
    """Plan B: el usuario descarga el PDF a mano en la ventana o en su navegador."""
    carpeta = Path.home() / "Downloads"
    fin = time.time() + segundos
    while time.time() < fin:
        for p in sorted(carpeta.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
            try:
                if p.stat().st_mtime >= desde and p.stat().st_size > 1000 and b"%PDF-" in p.read_bytes()[:1024]:
                    return p
            except OSError:
                continue
        time.sleep(2)
    return None

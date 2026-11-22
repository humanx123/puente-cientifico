"""Diagnóstico y reparación de la red de la app (Ajustes → Diagnóstico).

Comprueba cada servicio por cada ruta disponible (directa y túnel) y propone/aplica reparaciones:
reiniciar Tor (cerrando copias huérfanas, con puentes Snowflake si no conecta), reordenar espejos de
Sci-Hub y dominios de Anna's Archive para que los que funcionan vayan primero, elegir un espejo de
LibGen que responda y ajustar el alcance del túnel.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
import urllib.parse

import requests

from . import freellmapi, llm, resolver, tunel
from .config import load_settings, save_settings

ESPEJOS_LIBGEN = ["rs", "is", "li", "gs", "st"]
_ultimo: dict = {}


def _r(grupo, nombre, ruta, ok, detalle, ms=None, dato=None):
    return {"grupo": grupo, "nombre": nombre, "ruta": ruta, "ok": ok, "detalle": detalle, "ms": ms, "dato": dato}


def _medir(fn):
    t0 = time.time()
    try:
        ok, detalle, dato = fn()
    except Exception as e:
        ok, detalle, dato = False, f"{type(e).__name__}: {str(e)[:120]}", None
    return ok, detalle, round((time.time() - t0) * 1000), dato


def _sesion(servicio, ruta):
    from .literature import sesion
    return sesion(servicio, ruta)


def _rutas() -> list[str]:
    t = tunel.estado()
    return ["directo", "tunel"] if (t["modo"] != "directo" and t["estado"] == "listo") else ["directo"]


def _probar_libgen(espejo, ruta):
    def f():
        r = _sesion("libgen", ruta).get(f"https://libgen.{espejo}/index.php", params={"req": "biology", "res": 25}, timeout=30)
        n = len(set(re.findall(r"md5=([0-9a-fA-F]{32})", r.text)))
        if r.status_code == 200 and n:
            return True, f"{n} resultados de prueba", espejo
        return False, f"HTTP {r.status_code}, " + ("página sin resultados (bloqueo o mantenimiento)" if r.status_code == 200 else "sin acceso"), espejo
    return f


def _probar_annas(base, ruta):
    from .annas import describir_respuesta
    def f():
        r = _sesion("annas", ruta).get(base + "/search", params={"q": "biology", "display": "table"}, timeout=30)
        n = len(set(re.findall(r"/md5/([0-9a-f]{32})", r.text)))
        if r.status_code == 200 and n:
            return True, f"{n} resultados de prueba", base
        return False, describir_respuesta(r), base
    return f


def _annas_por_navegador(dominios) -> list[dict]:
    from . import navegador
    if not dominios or not navegador.disponible():
        return []
    out = []
    for d in dominios:
        base = d if d.startswith("http") else "https://" + d
        def f(base=base):
            r = navegador.obtener_texto(base, base + "/search?q=biology&display=table")
            if not r:
                return False, "el navegador integrado no superó la verificación", base
            n = len(set(re.findall(r"/md5/([0-9a-f]{32})", r[1] or "")))
            if r[0] == 200 and n:
                return True, f"{n} resultados de prueba (navegador integrado)", base
            return False, f"navegador integrado: HTTP {r[0]}, sin resultados", base
        ok, det, ms, dato = _medir(f)
        out.append(_r("Anna's Archive", urllib.parse.urlsplit(base).hostname, "navegador", ok, det, ms, dato))
        if ok:
            break  # basta uno: cada prueba abre una sesión en la ventana y tarda
    return out


def _probar_scihub(base, ruta):
    def f():
        r = _sesion("scihub", ruta).get(base, timeout=25)
        if resolver.es_bloqueo(r.text, r.status_code):
            return False, "pide verificación o bloquea (reto anti-robots / DDoS-Guard)", base
        if r.status_code == 200:
            return True, "responde", base
        return False, f"HTTP {r.status_code}", base
    return f


def ejecutar() -> dict:
    s = load_settings()["literatura"]
    res: list[dict] = []
    # --- Básicos
    def internet():
        r = requests.get("https://api.crossref.org/works", params={"rows": 0}, timeout=20)
        return r.status_code == 200, "conexión a internet correcta" if r.status_code == 200 else f"HTTP {r.status_code}", None
    ok, det, ms, _ = _medir(internet)
    res.append(_r("Conexión", "Internet (Crossref)", "directo", ok, det, ms))

    def openalex():
        from .literature import probar_openalex
        p = probar_openalex()
        return p["ok"], (f"{p['restantes']} de {p['limite']} créditos hoy" + ("" if p["con_clave"] else " · sin clave")) if p["ok"] else f"HTTP {p['codigo']}", p
    ok, det, ms, dato = _medir(openalex)
    res.append(_r("Conexión", "OpenAlex", "directo", ok, det, ms, dato))

    def ia():
        cfg = llm.config_activa()
        if cfg["proveedor"] != "freellmapi":
            return True, f"proveedor {cfg['proveedor']}", None
        e = freellmapi.estado(cfg)
        return e["corriendo"] and e["clave_valida"], ("activo y con clave" if e["clave_valida"] else "sin clave válida") if e["corriendo"] else "no responde", None
    ok, det, ms, _ = _medir(ia)
    res.append(_r("Conexión", "IA (FreeLLMAPI)", "directo", ok, det, ms))

    try:
        import server
        nativa = server.WINDOW.get("ventana") is not None
    except Exception:
        nativa = False
    res.append(_r("App", "Ventana nativa (verificación de revistas)", "-", nativa,
                  "disponible" if nativa else "no disponible: la app se abrió en el navegador o hay dos copias abiertas"))

    # --- Túnel
    t = tunel.estado()
    if t["modo"] == "tor":
        if t["estado"] in ("apagado", "error"):
            try:
                tunel.iniciar()
                tunel.esperar_listo(75)
            except Exception:
                pass
            t = tunel.estado()
        listo = t["estado"] == "listo"
        res.append(_r("Túnel", "Tor", "tunel", listo, f"{t['estado']} {t['progreso']}% · {t['mensaje'] or ''}".strip(" ·")))
        if listo:
            c = tunel.comprobar()
            res.append(_r("Túnel", "Salida por Tor", "tunel", c["ok"], c["detalle"]))
    elif t["modo"] == "proxy":
        res.append(_r("Túnel", "Proxy de VPN", "tunel", True, f"{s.get('proxy_tipo')}://{s.get('proxy_host')}:{s.get('proxy_puerto')}"))
    else:
        res.append(_r("Túnel", "Túnel", "-", True, "desactivado (conexión directa)"))

    # --- Servicios bloqueables, en paralelo por ruta
    rutas = _rutas()
    tareas = []
    for ruta in rutas:
        for e in ESPEJOS_LIBGEN:
            tareas.append(("LibGen", f"libgen.{e}", ruta, _probar_libgen(e, ruta)))
        for d in s.get("annas_dominios") or []:
            base = d if d.startswith("http") else "https://" + d
            tareas.append(("Anna's Archive", urllib.parse.urlsplit(base).hostname, ruta, _probar_annas(base, ruta)))
        for m in [s["scihub_url"]] + [x for x in s.get("scihub_espejos", []) if x != s["scihub_url"]]:
            tareas.append(("Sci-Hub", urllib.parse.urlsplit(m).hostname, ruta, _probar_scihub(m.rstrip("/"), ruta)))
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futuros = {ex.submit(_medir, fn): (g, n, r) for g, n, r, fn in tareas}
        for fut in cf.as_completed(futuros):
            g, n, r = futuros[fut]
            ok, det, ms, dato = fut.result()
            res.append(_r(g, n, r, ok, det, ms, dato))
    # Anna's Archive sin respuesta para Python: probar como lo hace la búsqueda real, con el navegador integrado
    if not _que_funciona(res, "Anna's Archive"):
        res.extend(_annas_por_navegador(s.get("annas_dominios") or []))
    orden ={"Conexión": 0, "App": 1, "Túnel": 2, "LibGen": 3, "Anna's Archive": 4, "Sci-Hub": 5}
    res.sort(key=lambda x: (orden.get(x["grupo"], 9), x["nombre"], x["ruta"]))
    _ultimo.clear()
    _ultimo.update(resultados=res, cuando=time.time())
    return {"resultados": res, "sugerencias": sugerencias(res), "rutas": rutas}


def _que_funciona(res, grupo):
    return [x for x in res if x["grupo"] == grupo and x["ok"]]


def sugerencias(res) -> list[str]:
    out = []
    s = load_settings()["literatura"]
    t = [x for x in res if x["grupo"] == "Túnel" and x["nombre"] == "Tor"]
    if t and not t[0]["ok"]:
        out.append("Reiniciar Tor" + (" con puentes Snowflake" if s.get("tor_puentes", "ninguno") == "ninguno" else ""))
    for g in ("LibGen", "Anna's Archive", "Sci-Hub"):
        bien = _que_funciona(res, g)
        if not bien:
            out.append(f"{g}: no responde por ninguna ruta" + (" (prueba activar el túnel Tor)" if s.get("tunel", "directo") == "directo" else ""))
        else:
            out.append(f"{g}: usar primero {bien[0]['nombre']} ({ {'tunel': 'túnel', 'navegador': 'navegador integrado'}.get(bien[0]['ruta'], 'directo') })")
    if s.get("tunel_alcance") == "todo":
        out.append("Limitar el túnel a los sitios bloqueados (OpenAlex por Tor siempre responde 429)")
    if not any(x["nombre"].startswith("Ventana nativa") and x["ok"] for x in res):
        out.append("Cierra todas las ventanas de la app y ábrela una sola vez desde el acceso directo")
    return out


def reparar() -> dict:
    res = _ultimo.get("resultados") or ejecutar()["resultados"]
    s = load_settings()["literatura"]
    cambios, acciones = {}, []
    # Tor
    tor = [x for x in res if x["grupo"] == "Túnel" and x["nombre"] == "Tor"]
    if tor and not tor[0]["ok"]:
        tunel.detener()
        tunel._cerrar_huerfanos()
        tunel.iniciar()
        try:
            tunel.esperar_listo(80)
            acciones.append("Tor reiniciado y conectado.")
        except RuntimeError:
            save_settings({"literatura": {"tor_puentes": "snowflake"}})
            tunel.detener()
            tunel.iniciar()
            try:
                tunel.esperar_listo(120)
                acciones.append("Tor no conectaba directamente: se activaron los puentes Snowflake y ya conecta.")
            except RuntimeError as e:
                acciones.append(f"Tor sigue sin conectar ({e}). Se deja la conexión directa para no bloquear las búsquedas.")
                cambios["tunel"] = "directo"
    # Alcance
    if s.get("tunel_alcance") == "todo":
        cambios["tunel_alcance"] = "bloqueados"
        acciones.append("El túnel ahora solo se usa para Sci-Hub, LibGen y Anna's Archive.")
    # LibGen
    bien = _que_funciona(res, "LibGen")
    if bien and not any(x["dato"] == s.get("libgen_espejo") for x in bien):
        cambios["libgen_espejo"] = bien[0]["dato"]
        acciones.append(f"Espejo de LibGen cambiado a libgen.{bien[0]['dato']}.")
    # Anna's: dominios que funcionan primero
    bien = [x["dato"].replace("https://", "") for x in _que_funciona(res, "Anna's Archive")]
    if bien:
        actual = s.get("annas_dominios") or []
        nuevo = list(dict.fromkeys(bien + actual))
        if nuevo != actual:
            cambios["annas_dominios"] = nuevo
            acciones.append(f"Anna's Archive: {bien[0]} pasa a ser el primer dominio.")
    # Sci-Hub: espejos que responden primero
    bien = [x["dato"] for x in _que_funciona(res, "Sci-Hub")]
    if bien:
        espejos = [s["scihub_url"]] + s.get("scihub_espejos", [])
        nuevo = list(dict.fromkeys(bien + espejos))
        if nuevo[0] != s["scihub_url"]:
            cambios["scihub_url"] = nuevo[0]
            cambios["scihub_espejos"] = nuevo
            acciones.append(f"Sci-Hub: {urllib.parse.urlsplit(nuevo[0]).hostname} pasa a ser el espejo principal.")
    if cambios:
        save_settings({"literatura": cambios})
    if not acciones:
        acciones.append("No hacía falta reparar nada automáticamente.")
    return {"acciones": acciones, "diagnostico": ejecutar()}

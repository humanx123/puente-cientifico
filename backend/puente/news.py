"""Noticias, convocatorias y eventos científicos (science-hub adaptado al español).

Igual que science-hub: fuentes RSS o HTML con selectores, etiquetas por palabras clave
(nivel / área / categoría), deduplicación por uid y límite de elementos guardados.
En lugar de GitHub Actions, la app actualiza en segundo plano cada N horas.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from . import db
from .config import BASE_DIR, load_settings

log = logging.getLogger("noticias")
SEMILLA = BASE_DIR / "datos" / "fuentes_noticias.json"
MAX_POR_FUENTE = 25
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PuenteCientifico/1.0"

NIVEL = {
    "Estudiantes": ["estudiante", "alumno", "bachiller", "preparatoria", "secundaria", "universitari", "licenciatura",
                    "olimpiada", "becari", "joven", "escolar"],
    "Investigadores": ["investigador", "posdoc", "postdoc", "doctorado", "posgrado", "sni ", "sistema nacional de investigadores",
                       "tesis", "artículo científico", "revista científica", "nature", "science", "the lancet", "cell"],
    "Público general": [],
}
AREA = {
    "Medicina y salud": ["salud", "médic", "medicina", "hospital", "enfermedad", "cáncer", "paciente", "vacuna", "virus",
                         "sarampión", "covid", "gripe", "dengue", "fármaco", "clínic", "epidemi", "pandemia", "brote"],
    "Biología": ["biolog", "especie", "célula", "gen ", "genes", "genoma", "adn", "evoluci", "animal", "planta", "ecosistema",
                 "biodiversidad", "bacteria", "microb", "neuron", "cerebro"],
    "Física": ["físic", "cuántic", "partícula", "átomo", "láser", "relatividad", "materia oscura", "fusión nuclear"],
    "Química": ["químic", "molécula", "compuesto", "reacción", "catalizador", "polímero", "material"],
    "Matemáticas": ["matemátic", "teorema", "algoritmo", "estadístic", "geometr", "ecuación"],
    "Computación e IA": ["inteligencia artificial", " ia ", "ia,", "machine learning", "aprendizaje automático", "robot",
                         "computación", "software", "chatgpt", "modelo de lenguaje", "datos", "ciberseguridad", "cuántica"],
    "Espacio y astronomía": ["espacio", "nasa", "esa ", "planeta", "estrella", "galaxia", "telescopio", "asteroide", "luna",
                             "marte", "astronom", "cometa", "agujero negro", "satélite", "cohete"],
    "Tierra y clima": ["clima", "climático", "calentamiento", "sismo", "terremoto", "volcán", "océano", "glaciar", "sequía",
                       "huracán", "contaminación", "medio ambiente", "ambiental", "emisiones"],
    "Ingeniería y tecnología": ["ingenier", "tecnolog", "energía", "batería", "solar", "electrónic", "semiconductor", "chip"],
    "Otras áreas": [],
}
CATEGORIA = {
    "Convocatorias y becas": ["convocatoria", "beca", "becas", "financiamiento", "fondos", "registro abierto", "inscripción",
                              "postulación", "plazo", "fecha límite"],
    "Olimpiadas y concursos": ["olimpiada", "concurso", "certamen", "competencia", "premio", "galardón", "hackathon", "reto"],
    "Eventos y cursos": ["congreso", "simposio", "seminario", "taller", "curso", "conferencia", "foro", "feria",
                         "jornada", "webinar", "semana de la ciencia", "noche de las estrellas"],
    "Investigación": ["estudio", "investigación", "investigadores", "descubren", "hallazgo", "revela", "publicado en",
                      "científicos", "ensayo"],
    "Políticas y financiamiento": ["secihti", "conahcyt", "conacyt", "ministerio", "presupuesto", "ley de ciencia",
                                   "política científica", "gobierno"],
    "Divulgación": [],
    "Noticias": [],
}


def etiquetar(texto: str, base: dict) -> dict:
    t = " " + texto.lower() + " "
    out = {}
    for clave, mapa in (("nivel", NIVEL), ("area", AREA), ("categoria", CATEGORIA)):
        s = set(base.get(clave, []))
        for tag, kws in mapa.items():
            if any(k in t for k in kws):
                s.add(tag)
        out[clave] = s
    if not out["area"]:
        out["area"].add("Otras áreas")
    if not out["nivel"]:
        out["nivel"].add("Público general")
    if not out["categoria"]:
        out["categoria"].add("Noticias")
    return {k: sorted(v) for k, v in out.items()}


def uid(fuente: str, titulo: str, enlace: str) -> str:
    return hashlib.sha1(f"{fuente}|{titulo.strip()}|{enlace.strip()}".encode("utf-8")).hexdigest()[:16]


MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


def normalizar_fecha(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return "-".join(m.groups())
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", raw)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-záé]{3})[a-záé]*\.?\s+(?:de\s+)?(\d{4})", raw.lower())
    if m and m.group(2)[:3] in MESES:
        try:
            return datetime(int(m.group(3)), MESES[m.group(2)[:3]], int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _limpiar_html(s: str) -> str:
    if not s:
        return ""
    return " ".join(BeautifulSoup(s, "html.parser").get_text(" ").split())[:400]


# ---------------------------------------------------------------------------
# Raspadores (science-hub rss_scraper / html_scraper)
# ---------------------------------------------------------------------------
def raspar_rss(f: dict) -> list[dict]:
    r = requests.get(f["url"], headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS ilegible ({feed.get('bozo_exception')})")
    items = []
    for e in feed.entries[:MAX_POR_FUENTE * 2]:
        titulo = (getattr(e, "title", "") or "").strip()
        enlace = (getattr(e, "link", "") or "").strip()
        if not titulo or not enlace:
            continue
        resumen = _limpiar_html(getattr(e, "summary", "") or "")
        fecha_raw = getattr(e, "published", "") or getattr(e, "updated", "")
        items.append({"titulo": titulo, "enlace": enlace, "resumen": resumen, "fecha_raw": fecha_raw})
    return items


def raspar_html(f: dict) -> list[dict]:
    sel = json.loads(f.get("selectores") or "{}") if isinstance(f.get("selectores"), str) else (f.get("selectores") or {})
    r = requests.get(f["url"], headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    sopa = BeautifulSoup(r.text, "html.parser")
    lista = sopa.select(sel.get("lista") or "article, li")
    base = f.get("base_url") or f["url"]
    items = []
    for nodo in lista[:MAX_POR_FUENTE * 2]:
        a = nodo.select_one(sel.get("enlace") or "a[href]")
        t = nodo.select_one(sel["titulo"]) if sel.get("titulo") else a
        if not a or not t:
            continue
        titulo = " ".join(t.get_text(" ").split())
        if len(titulo) < 6:
            continue
        fecha = nodo.select_one(sel["fecha"]).get_text(" ") if sel.get("fecha") and nodo.select_one(sel["fecha"]) else ""
        items.append({"titulo": titulo, "enlace": urljoin(base, a.get("href", "")), "resumen": "", "fecha_raw": fecha})
    return items


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def sembrar() -> None:
    if db.row("SELECT COUNT(*) n FROM fuentes_noticias")["n"]:
        return
    try:
        data = json.loads(SEMILLA.read_text(encoding="utf-8"))["fuentes"]
    except (OSError, ValueError, KeyError):
        return
    for f in data:
        guardar_fuente(f)


def fuentes() -> list[dict]:
    out = db.rows("SELECT * FROM fuentes_noticias ORDER BY organizacion, nombre")
    for f in out:
        f["etiquetas"] = json.loads(f["etiquetas"] or "{}")
        f["selectores"] = json.loads(f["selectores"] or "{}")
        f["n"] = db.row("SELECT COUNT(*) n FROM noticias WHERE fuente_id=?", (f["id"],))["n"]
    return out


def guardar_fuente(f: dict) -> dict:
    fid = (f.get("id") or re.sub(r"\W+", "_", f.get("nombre", "fuente").lower())[:40]).strip("_")
    if not f.get("url") or not f.get("nombre"):
        raise ValueError("La fuente necesita nombre y URL.")
    etiquetas = dict(f.get("etiquetas") or {})
    if f.get("filtro"):
        etiquetas["_filtro"] = f["filtro"]
    with db.tx() as c:
        c.execute(
            "INSERT INTO fuentes_noticias(id, organizacion, tipo_org, nombre, tipo, url, base_url, selectores, etiquetas, activa)"
            " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET organizacion=excluded.organizacion,"
            " tipo_org=excluded.tipo_org, nombre=excluded.nombre, tipo=excluded.tipo, url=excluded.url,"
            " base_url=excluded.base_url, selectores=excluded.selectores, etiquetas=excluded.etiquetas, activa=excluded.activa",
            (fid, f.get("organizacion") or f["nombre"], f.get("tipo_org", "medio"), f["nombre"], f.get("tipo", "rss"),
             f["url"], f.get("base_url", ""), json.dumps(f.get("selectores") or {}, ensure_ascii=False),
             json.dumps(etiquetas, ensure_ascii=False), int(f.get("activa", 1))),
        )
    return db.row("SELECT * FROM fuentes_noticias WHERE id=?", (fid,))


def borrar_fuente(fid: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM fuentes_noticias WHERE id=?", (fid,))
        c.execute("DELETE FROM noticias WHERE fuente_id=? AND guardada=0", (fid,))


def activar_fuente(fid: str, activa: bool) -> None:
    with db.tx() as c:
        c.execute("UPDATE fuentes_noticias SET activa=? WHERE id=?", (int(activa), fid))


# ---------------------------------------------------------------------------
# Recolección
# ---------------------------------------------------------------------------
_estado = {"en_curso": False, "ultima": None, "resultado": None}
_lock = threading.Lock()


def recolectar_fuente(f: dict) -> int:
    etiquetas = f["etiquetas"] if isinstance(f["etiquetas"], dict) else json.loads(f["etiquetas"] or "{}")
    filtro = etiquetas.pop("_filtro", None)
    crudos = raspar_rss(f) if f["tipo"] == "rss" else raspar_html(f)
    if filtro:
        rx = re.compile(filtro, re.I)
        crudos = [i for i in crudos if rx.search(i["titulo"] + " " + i["resumen"])]
    nuevos = 0
    with db.tx() as c:
        for it in crudos[:MAX_POR_FUENTE]:
            tags = etiquetar(it["titulo"] + " " + it["resumen"], etiquetas)
            u = uid(f["id"], it["titulo"], it["enlace"])
            cur = c.execute(
                "INSERT OR IGNORE INTO noticias(uid, fuente_id, organizacion, tipo_org, titulo, enlace, resumen, fecha,"
                " nivel, area, categoria) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (u, f["id"], f["organizacion"], f["tipo_org"], it["titulo"], it["enlace"], it["resumen"],
                 normalizar_fecha(it["fecha_raw"]) or datetime.now().strftime("%Y-%m-%d"),
                 json.dumps(tags["nivel"], ensure_ascii=False), json.dumps(tags["area"], ensure_ascii=False),
                 json.dumps(tags["categoria"], ensure_ascii=False)),
            )
            nuevos += cur.rowcount
        c.execute("UPDATE fuentes_noticias SET ultimo_estado=?, ultima_vez=datetime('now','localtime') WHERE id=?",
                  (f"ok · {len(crudos)} elementos" if crudos else "0 elementos (revisar selectores)", f["id"]))
    return nuevos


def recolectar_todo() -> dict:
    with _lock:
        if _estado["en_curso"]:
            return dict(_estado)
        _estado["en_curso"] = True
    ok, fallidas, nuevos = 0, [], 0
    try:
        for f in fuentes():
            if not f["activa"]:
                continue
            try:
                nuevos += recolectar_fuente(f)
                ok += 1
            except Exception as e:
                fallidas.append(f["nombre"])
                with db.tx() as c:
                    c.execute("UPDATE fuentes_noticias SET ultimo_estado=?, ultima_vez=datetime('now','localtime') WHERE id=?",
                              ("error: " + str(e)[:150], f["id"]))
        maximo = int(load_settings()["noticias"].get("max_elementos", 600))
        with db.tx() as c:  # como science-hub: conservar solo los más recientes (excepto guardados)
            c.execute("DELETE FROM noticias WHERE guardada=0 AND uid NOT IN"
                      " (SELECT uid FROM noticias ORDER BY fecha DESC, recogida DESC LIMIT ?)", (maximo,))
        _estado["resultado"] = {"ok": ok, "fallidas": fallidas, "nuevos": nuevos}
        _estado["ultima"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    finally:
        _estado["en_curso"] = False
    return dict(_estado)


def estado() -> dict:
    return dict(_estado)


def listar(q: str = "", nivel: str = "", area: str = "", categoria: str = "", fuente: str = "",
           solo_guardadas: bool = False, no_leidas: bool = False, limite: int = 300) -> list[dict]:
    where, params = ["1=1"], []
    if q:
        where.append("(titulo LIKE ? OR resumen LIKE ? OR organizacion LIKE ?)")
        params += [f"%{q}%"] * 3
    for col, val in (("nivel", nivel), ("area", area), ("categoria", categoria)):
        if val:
            where.append(f"{col} LIKE ?")
            params.append(f'%"{val}"%')
    if fuente:
        where.append("fuente_id=?")
        params.append(fuente)
    if solo_guardadas:
        where.append("guardada=1")
    if no_leidas:
        where.append("leida=0")
    out = db.rows(f"SELECT * FROM noticias WHERE {' AND '.join(where)} ORDER BY fecha DESC, recogida DESC LIMIT ?",
                  (*params, limite))
    for n in out:
        for k in ("nivel", "area", "categoria"):
            n[k] = json.loads(n[k] or "[]")
    return out


def marcar(uid_: str, leida: bool | None = None, guardada: bool | None = None) -> None:
    with db.tx() as c:
        if leida is not None:
            c.execute("UPDATE noticias SET leida=? WHERE uid=?", (int(leida), uid_))
        if guardada is not None:
            c.execute("UPDATE noticias SET guardada=? WHERE uid=?", (int(guardada), uid_))


def facetas() -> dict:
    return {"nivel": list(NIVEL), "area": list(AREA), "categoria": list(CATEGORIA)}


def probar_fuente(f: dict) -> list[dict]:
    """Equivalente a `main.py --test <id>` de science-hub: no guarda nada."""
    items = raspar_rss(f) if f.get("tipo", "rss") == "rss" else raspar_html(f)
    return [dict(i, etiquetas=etiquetar(i["titulo"] + " " + i["resumen"], f.get("etiquetas") or {})) for i in items[:15]]


def programador(stop: threading.Event) -> None:
    """Sustituye al cron de GitHub Actions: recolecta al iniciar y cada N horas."""
    time.sleep(4)
    while not stop.is_set():
        try:
            recolectar_todo()
        except Exception as e:
            log.warning("Fallo en la recolección: %s", e)
        horas = max(0.5, float(load_settings()["noticias"].get("intervalo_horas", 3)))
        stop.wait(horas * 3600)

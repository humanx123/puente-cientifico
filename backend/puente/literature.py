"""Búsqueda y descarga de literatura.

- Búsqueda de metadatos en OpenAlex (PageBridge).
- Descarga de PDF de acceso abierto (OpenAlex best_oa_location / Unpaywall).
- Descarga vía Sci-Hub con la lógica de SciHubEVA: tipos de consulta (DOI, PMID, URL,
  PDF, texto), consultas por rango «{1-10}», listas por lote, rotación de espejos,
  XPath configurables, detección de CAPTCHA que resuelve el usuario y DDoS-Guard.
"""
from __future__ import annotations

import base64
import ipaddress
import re
import socket
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import fitz
import requests
import urllib3
from lxml.etree import HTML
from pathvalidate import sanitize_filename

from . import db, library
from .config import CACHE_DIR, load_settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OPENALEX = "https://api.openalex.org/works"
RANGO_RE = re.compile(r"\{\d+-\d+\}")
DOI_RE = re.compile(r"\b(10[.][0-9]{4,}(?:[.][0-9]+)*/(?:(?![\"&'<>])\S)+)\b")
MAX_PDF = 150 * 1024 * 1024
DESCARGAS_DIR = CACHE_DIR / "descargas"
DESCARGAS_DIR.mkdir(parents=True, exist_ok=True)


class LitError(Exception):
    pass


# ---------------------------------------------------------------------------
# Utilidades de consulta (SciHubEVA api_utils)
# ---------------------------------------------------------------------------
def es_rango(q: str) -> bool:
    return len(RANGO_RE.findall(q)) == 1


def expandir_rango(q: str) -> list[str]:
    patron = RANGO_RE.findall(q)[0]
    desde, hasta = patron.strip("{}").split("-")
    if int(hasta) - int(desde) > 500:
        raise LitError("El rango es demasiado grande (máximo 500 elementos).")
    if len(desde) == len(hasta):
        fmt = "{:0>" + str(len(desde)) + "d}"
        items = [fmt.format(i) for i in range(int(desde), int(hasta) + 1)]
    else:
        items = [str(i) for i in range(int(desde), int(hasta) + 1)]
    return [q.replace(patron, i) for i in items]


def tipo_consulta(q: str | None) -> str:
    if not q:
        return "texto"
    if q.startswith("http://") or q.startswith("https://"):
        return "pdf" if q.lower().split("?")[0].endswith(".pdf") else "url"
    if q.isdigit():
        return "pmid"
    if q.lower().startswith("doi:") or DOI_RE.match(q) or normalizar_doi(q):
        return "doi"
    return "texto"


def normalizar_doi(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    v = valor.strip()
    if v.lower().startswith("doi:"):
        v = v[4:].strip()
    try:
        partes = urllib.parse.urlsplit(v)
        if partes.scheme in ("http", "https") and partes.hostname in ("doi.org", "www.doi.org", "dx.doi.org"):
            v = urllib.parse.unquote(partes.path.lstrip("/"))
    except ValueError:
        return None
    return v.lower() if re.fullmatch(r"10\.[0-9]{4,9}/\S+", v) else None


def url_publica(url: str) -> str:
    """Evita que una redirección o un enlace manipulado apunte a la red local (PageBridge)."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        raise LitError("Dirección no válida.") from None
    if p.scheme not in ("http", "https") or not p.hostname:
        raise LitError("Solo se admiten direcciones http(s).")
    host = p.hostname
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        if host in ("localhost",) or host.endswith((".local", ".lan", ".internal")):
            raise LitError("La dirección apunta a la red local; se detuvo la descarga.") from None
        try:
            ips = [ipaddress.ip_address(r[4][0]) for r in socket.getaddrinfo(host, None)]
        except (OSError, ValueError):
            raise LitError(f"No se pudo resolver {host}. Revisa tu conexión o el espejo.") from None
    for ip in ips:
        # 198.18.0.0/15 lo usan proxies TUN (Clash, etc.) para DNS sintético
        if not (ip.is_global or ip in ipaddress.ip_network("198.18.0.0/15")):
            raise LitError("La dirección apunta a la red local; se detuvo la descarga.")
    return url


# ---------------------------------------------------------------------------
# Sesión HTTP con proxy (SciHubEVA network_utils)
# ---------------------------------------------------------------------------
def sesion() -> requests.Session:
    s = load_settings()["literatura"]
    sess = requests.Session()
    sess.headers.update({"User-Agent": s["agente_usuario"], "Accept-Language": "es,en;q=0.8"})
    if s.get("proxy_activo"):
        auth = ""
        if s.get("proxy_usuario"):
            auth = urllib.parse.quote(s["proxy_usuario"]) + ":" + urllib.parse.quote(s.get("proxy_clave", "")) + "@"
        esquema = "socks5h" if s.get("proxy_tipo") == "socks5" else "http"
        proxy = f"{esquema}://{auth}{s['proxy_host']}:{s['proxy_puerto']}"
        sess.proxies = {"http": proxy, "https": proxy}
    adapter = requests.adapters.HTTPAdapter(max_retries=int(s.get("reintentos", 3)))
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess


def _timeout() -> float:
    return max(3.0, load_settings()["literatura"].get("tiempo_espera_ms", 15000) / 1000.0)


# ---------------------------------------------------------------------------
# OpenAlex (PageBridge literature.search)
# ---------------------------------------------------------------------------
def _limpiar(v, n):
    if not isinstance(v, str):
        return None
    v = " ".join(v.split())[:n]
    return v or None


def _obra(raw: dict) -> dict | None:
    titulo = _limpiar(raw.get("display_name") or raw.get("title"), 800)
    doi = normalizar_doi(raw.get("doi"))
    ident = _limpiar(raw.get("id"), 512) or doi
    if not titulo or not ident:
        return None
    extras = raw.get("locations") if isinstance(raw.get("locations"), list) else []
    ubicaciones = [x for x in [raw.get("best_oa_location"), raw.get("primary_location")] + extras[:60] if isinstance(x, dict)]
    pdf = next((x.get("pdf_url") for x in ubicaciones if x.get("is_oa") and x.get("pdf_url")), None)
    pagina = next((x.get("landing_page_url") for x in ubicaciones if x.get("landing_page_url")), None)
    pagina = pagina or (f"https://doi.org/{doi}" if doi else None)
    autores = []
    for a in raw.get("authorships") or []:
        nombre = _limpiar((a.get("author") or {}).get("display_name"), 120)
        if nombre and nombre not in autores:
            autores.append(nombre)
        if len(autores) >= 8:
            break
    revista = next((_limpiar((x.get("source") or {}).get("display_name"), 240) for x in ubicaciones
                    if isinstance(x.get("source"), dict) and x["source"].get("display_name")), None)
    oa = raw.get("open_access") or {}
    return {
        "id": ident, "titulo": titulo, "autores": autores, "anio": raw.get("publication_year"),
        "revista": revista, "doi": doi, "pagina_url": pagina, "pdf_url": pdf,
        "acceso_abierto": bool(oa.get("is_oa")), "estado_oa": oa.get("oa_status"),
        "citas": raw.get("cited_by_count"), "tipo": raw.get("type"),
        "en_biblioteca": bool(doi and db.row("SELECT 1 FROM documentos WHERE doi=? AND papelera IS NULL", (doi,))),
    }


def buscar(q: str, pagina: int = 1, solo_abierto: bool = False, desde: int | None = None, hasta: int | None = None,
           orden: str = "relevancia") -> dict:
    q = (q or "").strip()
    if not 1 <= len(q) <= 1024:
        raise LitError("Escribe un título, palabras clave o DOI (máximo 1024 caracteres).")
    cfg = load_settings()["literatura"]
    params = {
        "per_page": 25, "page": max(1, min(int(pagina), 400)),
        "select": "id,doi,display_name,publication_year,authorships,primary_location,best_oa_location,locations,"
                  "open_access,cited_by_count,type",
    }
    filtros = []
    doi = normalizar_doi(q)
    if doi:
        filtros.append("doi:https://doi.org/" + doi)
    else:
        params["search"] = q
    if solo_abierto:
        filtros.append("is_oa:true")
    if desde:
        filtros.append(f"from_publication_date:{int(desde)}-01-01")
    if hasta:
        filtros.append(f"to_publication_date:{int(hasta)}-12-31")
    if filtros:
        params["filter"] = ",".join(filtros)
    if orden == "citas":
        params["sort"] = "cited_by_count:desc"
    elif orden == "recientes":
        params["sort"] = "publication_date:desc"
    if cfg.get("openalex_correo"):
        params["mailto"] = cfg["openalex_correo"]
    if cfg.get("openalex_clave"):
        params["api_key"] = cfg["openalex_clave"]
    try:
        r = sesion().get(OPENALEX, params=params, timeout=30)
    except requests.RequestException as e:
        raise LitError("No se pudo conectar con OpenAlex: " + str(e)[:160]) from None
    if r.status_code == 429:
        raise LitError("OpenAlex limitó las peticiones. Espera un momento o añade tu correo/clave en Ajustes.")
    if r.status_code != 200:
        raise LitError(f"OpenAlex respondió HTTP {r.status_code}.")
    data = r.json()
    obras, vistos = [], set()
    for raw in data.get("results", []):
        o = _obra(raw)
        if o and (o["doi"] or o["id"]) not in vistos:
            vistos.add(o["doi"] or o["id"])
            obras.append(o)
    total = (data.get("meta") or {}).get("count") or 0
    return {"obras": obras, "total": total, "pagina": params["page"], "hay_mas": params["page"] * 25 < total}


def metadatos_doi(doi: str) -> dict | None:
    try:
        r = sesion().get(f"{OPENALEX}/https://doi.org/{urllib.parse.quote(doi, safe='/')}", timeout=20)
        if r.status_code == 200:
            return _obra(r.json())
    except requests.RequestException:
        pass
    return None


# ---------------------------------------------------------------------------
# Sci-Hub (SciHubEVA scihub_api)
# ---------------------------------------------------------------------------
def _xpath_urls(html_bytes: bytes, xpaths: list[str], base_url: str) -> list[str]:
    try:
        arbol = HTML(html_bytes)
    except Exception:
        return []
    if arbol is None:
        return []
    out = []
    for xp in xpaths:
        try:
            res = arbol.xpath(xp)
        except Exception:
            continue
        for el in res or []:
            src = el.attrib.get("src") or el.attrib.get("data") or el.attrib.get("href") if hasattr(el, "attrib") else None
            if src:
                out.append(src)
    # Otros formatos de página: meta citation_pdf_url, botones con location.href
    for meta in arbol.xpath('//meta[@name="citation_pdf_url"]/@content'):
        out.append(meta)
    texto = html_bytes.decode("utf-8", "ignore")
    for m in re.finditer(r"location\.href\s*=\s*['\"]([^'\"]+\.pdf[^'\"]*)['\"]", texto):
        out.append(m.group(1))
    for m in re.finditer(r"href\s*=\s*['\"]([^'\"]+\.pdf(?:[?#][^'\"]*)?)['\"]", texto):
        out.append(m.group(1))
    limpias = []
    for u in out:
        u = u.strip()
        if u.startswith("//"):
            u = urllib.parse.urlsplit(base_url).scheme + ":" + u
        u = urllib.parse.urljoin(base_url, u)
        u = u.split("#")[0]
        if u not in limpias:
            limpias.append(u)
    return limpias


def _info_captcha(resp: requests.Response) -> tuple[str | None, str | None]:
    s = load_settings()["literatura"]
    try:
        arbol = HTML(resp.content)
    except Exception:
        return None, None
    if arbol is None:
        return None, None
    cid = img = None
    for xp in s["xpath_captcha_id"]:
        r = arbol.xpath(xp)
        if r:
            cid = r[0].attrib.get("value")
            break
    for xp in s["xpath_captcha_img"]:
        r = arbol.xpath(xp)
        if r:
            img = urllib.parse.urljoin(resp.url, r[0].attrib.get("src", ""))
            break
    return cid, img


def _es_pdf(resp: requests.Response, cabeza: bytes) -> bool:
    return b"%PDF-" in cabeza[:1024] or resp.headers.get("Content-Type", "").lower().startswith("application/pdf")


# ---------------------------------------------------------------------------
# Trabajos de descarga
# ---------------------------------------------------------------------------
_trabajos: dict[str, dict] = {}
_lock = threading.Lock()


def _nuevo_trabajo(consulta: str, obra: dict | None, fuente: str) -> dict:
    t = {
        "id": uuid.uuid4().hex[:12], "consulta": consulta, "obra": obra, "fuente": fuente,
        "tipo": tipo_consulta(consulta), "estado": "en_cola", "registro": [], "documento_id": None,
        "captcha": None, "pagina_url": None, "creado": time.time(), "_evento": threading.Event(),
        "_respuesta": None, "_sesion": None, "_resp_captcha": None,
    }
    with _lock:
        _trabajos[t["id"]] = t
    return t


def _log(t: dict, msg: str, nivel: str = "info") -> None:
    t["registro"].append({"t": time.strftime("%H:%M:%S"), "nivel": nivel, "msg": msg})


def publico(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}


def listar_trabajos() -> list[dict]:
    with _lock:
        return [publico(t) for t in sorted(_trabajos.values(), key=lambda x: -x["creado"])]


def limpiar_trabajos() -> None:
    with _lock:
        for k in [k for k, t in _trabajos.items() if t["estado"] in ("ok", "error", "duplicado")]:
            del _trabajos[k]


def encolar(consultas: str | list[str], fuente: str | None = None, obra: dict | None = None) -> list[dict]:
    """Acepta una consulta, varias líneas, o un rango «10.1000/abc{1-9}» como en SciHubEVA."""
    if isinstance(consultas, str):
        lineas = [x.strip() for x in consultas.splitlines() if x.strip()]
    else:
        lineas = [x.strip() for x in consultas if x and x.strip()]
    expandidas: list[str] = []
    for l in lineas:
        expandidas.extend(expandir_rango(l) if es_rango(l) else [l])
    if not expandidas:
        raise LitError("Escribe al menos un DOI, PMID, URL o título.")
    if len(expandidas) > 500:
        raise LitError("Máximo 500 consultas por lote.")
    fuente = fuente or load_settings()["literatura"]["fuente"]
    creados = []
    for q in expandidas:
        t = _nuevo_trabajo(q, obra if len(expandidas) == 1 else None, fuente)
        creados.append(publico(t))
    threading.Thread(target=_procesar_cola, args=([c["id"] for c in creados],), daemon=True).start()
    return creados


def _procesar_cola(ids: list[str]) -> None:
    for jid in ids:
        t = _trabajos.get(jid)
        if not t:
            continue
        try:
            _procesar(t)
        except LitError as e:
            t["estado"] = "error"
            _log(t, str(e), "error")
        except Exception as e:  # nunca romper la cola
            t["estado"] = "error"
            _log(t, "Error inesperado: " + str(e)[:300], "error")
        db.conn().execute("INSERT INTO descargas(consulta, estado, mensaje, documento_id) VALUES (?,?,?,?)",
                          (t["consulta"], t["estado"], t["registro"][-1]["msg"] if t["registro"] else "", t["documento_id"]))
        db.conn().commit()


def _procesar(t: dict) -> None:
    cfg = load_settings()["literatura"]
    q = t["consulta"]
    doi = normalizar_doi(q)
    obra = t["obra"]
    _log(t, f"Consulta: {q} · tipo {t['tipo'].upper()}")
    if doi:
        ya = db.row("SELECT id FROM documentos WHERE doi=? AND papelera IS NULL", (doi,))
        if ya:
            t["estado"], t["documento_id"] = "duplicado", ya["id"]
            _log(t, "Ya está en tu biblioteca.", "ok")
            return
        if not obra:
            obra = metadatos_doi(doi)
            t["obra"] = obra
            if obra:
                _log(t, f"Metadatos de OpenAlex: «{obra['titulo'][:90]}»")
    sess = sesion()
    t["_sesion"] = sess
    intentos: list[tuple[str, str]] = []
    if t["tipo"] == "pdf":
        intentos.append(("directo", q))
    if t["fuente"] in ("auto", "abierto") and obra and obra.get("pdf_url"):
        intentos.append(("acceso abierto", obra["pdf_url"]))
    if t["fuente"] in ("auto", "scihub") and t["tipo"] != "pdf":
        espejos = [cfg["scihub_url"]] + [m for m in cfg.get("scihub_espejos", []) if m != cfg["scihub_url"]]
        for m in espejos:
            intentos.append(("sci-hub", m.rstrip("/")))
    if not intentos:
        t["pagina_url"] = (obra or {}).get("pagina_url")
        raise LitError("No hay PDF de acceso abierto para esta obra. Prueba la fuente «Sci-Hub» o abre la página.")
    t["estado"] = "buscando"
    ultimo_error = "No se encontró el PDF."
    for fuente, url in intentos:
        try:
            if fuente == "sci-hub":
                _log(t, f"Usando Sci-Hub: {url}")
                pdf_url = _resolver_scihub(t, sess, url, q, doi)
                if pdf_url is None:
                    continue
                _log(t, f"URL del PDF: {pdf_url}")
            else:
                _log(t, f"Probando fuente {fuente}: {url}")
                pdf_url = url
            ruta = _descargar(t, sess, pdf_url)
            if ruta is None:
                continue
            _importar(t, ruta, "sci-hub" if fuente == "sci-hub" else fuente)
            return
        except LitError as e:
            ultimo_error = str(e)
            _log(t, str(e), "aviso")
    t["pagina_url"] = t.get("pagina_url") or (obra or {}).get("pagina_url")
    raise LitError(ultimo_error + " Puedes abrir la página manualmente.")


def _resolver_scihub(t: dict, sess: requests.Session, base: str, q: str, doi: str | None) -> str | None:
    cfg = load_settings()["literatura"]
    url_publica(base)
    respuestas = []
    try:
        if doi:  # formato moderno: GET espejo/DOI (PageBridge)
            r = sess.get(f"{base}/{urllib.parse.quote(doi, safe='/():;@!$&=,+-._~')}", timeout=_timeout(), verify=False)
            respuestas.append(r)
        # formato clásico: POST request=consulta (SciHubEVA)
        if not doi or not _xpath_urls(respuestas[-1].content, cfg["xpaths_pdf"], respuestas[-1].url):
            r = sess.post(base, data={"request": q}, timeout=_timeout(), verify=False)
            respuestas.append(r)
    except requests.RequestException as e:
        raise LitError(f"El espejo {base} no responde: {str(e)[:120]}") from None
    for r in respuestas:
        if r.status_code == 403 and "ddos-guard" in r.text.lower():
            raise LitError("Bloqueado por DDoS-Guard en este espejo. Cambia de IP/proxy o usa FlareSolverr.")
        if r.status_code != 200:
            continue
        cabeza = r.content[:1024]
        if _es_pdf(r, cabeza):
            return r.url
        # Comprobación de DOI (PageBridge): la página debe referirse a la misma obra
        if doi:
            metas = HTML(r.content).xpath('//meta[@name="citation_doi"]/@content') if r.content else []
            if metas and normalizar_doi(metas[0]) and normalizar_doi(metas[0]) != doi:
                raise LitError("Sci-Hub devolvió un DOI distinto al solicitado; se descartó.")
        urls = _xpath_urls(r.content, cfg["xpaths_pdf"], r.url)
        if urls:
            return urls[0]
        texto = r.text.lower()
        if "captcha" in texto or "altcha" in texto:
            t["_resp_captcha"] = r
            return _resolver_captcha(t, sess, r)
        if "article not found" in texto or "статья не найдена" in texto or "not found" in texto[:4000]:
            raise LitError(f"El espejo {base} no tiene este artículo.")
    raise LitError(f"No se pudo obtener la URL del PDF en {base}.")


def _resolver_captcha(t: dict, sess: requests.Session, resp: requests.Response) -> str | None:
    cid, img = _info_captcha(resp)
    if not img:
        t["pagina_url"] = resp.url
        raise LitError("La página pide verificación humana que no se puede mostrar aquí. Ábrela en el navegador.")
    try:
        im = sess.get(img, timeout=_timeout(), verify=False)
        tipo = im.headers.get("Content-Type", "image/png").split(";")[0]
        datos = "data:" + tipo + ";base64," + base64.b64encode(im.content).decode()
    except requests.RequestException:
        raise LitError("No se pudo descargar la imagen del CAPTCHA.") from None
    t["captcha"] = {"imagen": datos, "pagina": resp.url}
    t["estado"] = "captcha"
    _log(t, "¡Aparece un CAPTCHA! Escribe el código que ves en la imagen.", "aviso")
    t["_evento"].clear()
    if not t["_evento"].wait(timeout=600):
        t["captcha"] = None
        raise LitError("Tiempo de espera del CAPTCHA agotado.")
    respuesta = t["_respuesta"]
    t["captcha"] = None
    t["estado"] = "descargando"
    if respuesta is None:
        raise LitError("CAPTCHA cancelado.")
    try:
        r = sess.post(resp.url, data={"answer": respuesta, "id": cid or ""}, timeout=_timeout(), verify=False)
    except requests.RequestException as e:
        raise LitError("Error al enviar el CAPTCHA: " + str(e)[:120]) from None
    if _es_pdf(r, r.content[:1024]):
        ruta = _guardar_bytes(r.content)
        t["_pdf_directo"] = ruta
        _log(t, "CAPTCHA superado.", "ok")
        return r.url
    urls = _xpath_urls(r.content, load_settings()["literatura"]["xpaths_pdf"], r.url)
    if urls:
        _log(t, "CAPTCHA superado.", "ok")
        return urls[0]
    raise LitError("CAPTCHA incorrecto.")


def responder_captcha(jid: str, respuesta: str | None) -> dict:
    t = _trabajos.get(jid)
    if not t or t["estado"] != "captcha":
        raise LitError("Este trabajo no está esperando un CAPTCHA.")
    t["_respuesta"] = respuesta.strip() if respuesta else None
    t["_evento"].set()
    return publico(t)


def _guardar_bytes(contenido: bytes) -> Path:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=DESCARGAS_DIR)
    f.write(contenido)
    f.close()
    return Path(f.name)


def _descargar(t: dict, sess: requests.Session, url: str) -> Path | None:
    directo = t.pop("_pdf_directo", None)
    if directo:
        return directo
    url_publica(url)
    t["estado"] = "descargando"
    _log(t, "Descargando PDF…")
    try:
        r = sess.get(url, timeout=max(_timeout(), 60), verify=False, stream=True)
    except requests.RequestException as e:
        raise LitError("Fallo al descargar el PDF: " + str(e)[:150]) from None
    if r.status_code != 200:
        raise LitError(f"La descarga respondió HTTP {r.status_code}.")
    destino = DESCARGAS_DIR / (uuid.uuid4().hex + ".pdf")
    total = 0
    cabeza = b""
    with open(destino, "wb") as f:
        for bloque in r.iter_content(64 * 1024):
            if not bloque:
                continue
            if len(cabeza) < 1024:
                cabeza += bloque[:1024 - len(cabeza)]
            total += len(bloque)
            if total > MAX_PDF:
                f.close()
                destino.unlink(missing_ok=True)
                raise LitError("El PDF supera el tamaño máximo (150 MB).")
            f.write(bloque)
    if b"%PDF-" not in cabeza:
        tipo = r.headers.get("Content-Type", "")
        destino_html = destino.read_bytes()
        destino.unlink(missing_ok=True)
        if "html" in tipo:
            if b"captcha" in destino_html.lower():
                fake = requests.Response()
                fake._content = destino_html
                fake.url = r.url
                fake.status_code = 200
                fake.headers["Content-Type"] = tipo
                pdf_url = _resolver_captcha(t, sess, fake)
                if pdf_url:
                    return _descargar(t, sess, pdf_url)
            urls = _xpath_urls(destino_html, load_settings()["literatura"]["xpaths_pdf"], r.url)
            if urls and urls[0] != url:
                return _descargar(t, sess, urls[0])
            t["pagina_url"] = r.url
            raise LitError("La fuente devolvió una página web en vez del PDF (puede requerir verificación).")
        raise LitError("El contenido descargado no es un PDF.")
    return destino


def _nombre_archivo(t: dict, ruta: Path) -> str:
    cfg = load_settings()["literatura"]
    obra = t.get("obra") or {}
    meta = {"author": "AUTOR_DESCONOCIDO", "title": "TITULO_DESCONOCIDO", "year": "AÑO_DESCONOCIDO", "id": ""}
    try:
        pdf = fitz.open(ruta)
        m = pdf.metadata or {}
        pdf.close()
        if m.get("author"):
            meta["author"] = m["author"]
        if m.get("title"):
            meta["title"] = m["title"]
        if (m.get("creationDate") or "")[2:6].isdigit():
            meta["year"] = m["creationDate"][2:6]
    except Exception:
        pass
    if obra.get("autores"):
        meta["author"] = obra["autores"][0]
    if obra.get("titulo"):
        meta["title"] = obra["titulo"]
    if obra.get("anio"):
        meta["year"] = str(obra["anio"])
    fmt = cfg.get("formato_nombre") or "{title}"
    if t["tipo"] in ("doi", "pmid"):
        meta["id"] = t["consulta"]
    else:
        for p in ("_{id}", "{id}_", "{id}"):
            fmt = fmt.replace(p, "")
    try:
        nombre = fmt.format(**meta)
    except (KeyError, IndexError, ValueError):
        nombre = meta["title"]
    nombre = sanitize_filename(nombre, replacement_text="-")[:150].strip() or "articulo"
    if not cfg.get("sobrescribir"):
        nombre += "_" + str(int(time.time() * 1000))[-6:]
    return nombre + ".pdf"


def _importar(t: dict, ruta: Path, origen: str) -> None:
    obra = t.get("obra") or {}
    cfg = load_settings()["literatura"]
    try:
        d = library.import_pdf(
            ruta, title=obra.get("titulo"), authors=", ".join(obra.get("autores") or []),
            year=obra.get("anio"), doi=obra.get("doi") or normalizar_doi(t["consulta"]), origen=origen,
        )
    finally:
        pass
    if cfg.get("guardar_copia_en"):
        try:
            carpeta = Path(cfg["guardar_copia_en"])
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = carpeta / _nombre_archivo(t, ruta)
            destino.write_bytes(ruta.read_bytes())
            _log(t, f"Copia guardada en: {destino}", "ok")
        except OSError as e:
            _log(t, f"No se pudo guardar la copia: {e}", "aviso")
    ruta.unlink(missing_ok=True)
    t["documento_id"] = d["id"]
    if d.get("duplicado"):
        t["estado"] = "duplicado"
        _log(t, "El PDF ya estaba en la biblioteca.", "ok")
    else:
        t["estado"] = "ok"
        _log(t, f"Importado a la biblioteca: «{d['titulo'][:90]}» ({d['paginas']} págs.)", "ok")


def historial(limite: int = 200) -> list[dict]:
    return db.rows("SELECT * FROM descargas ORDER BY id DESC LIMIT ?", (limite,))

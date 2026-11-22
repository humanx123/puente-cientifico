"""Anna's Archive (https://github.com/LilyLoops/annas-archive).

El repositorio es el código del sitio web (Flask + Elasticsearch), no un cliente: aquí se consulta una
instancia pública. El análisis sigue las plantillas del propio código:
- /search?q=&content=&ext=&lang=&sort=&page=&display=table  → filas con columnas fijas
  (templates/macros/aarecord_list.html): portada, título, autor, editorial, año, archivo, fuentes,
  idiomas, tipo de contenido, extensión, tamaño, id.
- Los resultados a partir del 11.º llegan dentro de comentarios HTML (carga diferida): se quitan.
- Descarga: API de miembros /dyn/api/fast_download.json?md5=&key= o, sin clave, por md5 en LibGen.

Los dominios cambian a menudo y algunos proveedores los bloquean por DNS: la lista es configurable
y puede resolverse con DNS sobre HTTPS (Cloudflare).
"""
from __future__ import annotations

import re
import socket
import threading
import urllib.parse

import requests
from bs4 import BeautifulSoup

from .config import load_settings

TIPOS = {
    "libros": "book_nonfiction", "ficcion": "book_fiction", "desconocido": "book_unknown",
    "articulos": "journal_article", "revistas": "magazine", "comics": "book_comic", "normas": "standards_document",
}
ORDEN = {"relevancia": "", "recientes": "newest", "antiguos": "oldest", "grandes": "largest", "pequenos": "smallest"}
COLUMNAS = ["portada", "titulo", "autor", "editorial", "anio", "archivo", "fuentes", "idiomas", "tipo",
            "extension", "tamano", "id"]
MD5_RE = re.compile(r"/md5/([0-9a-f]{32})")


class AnnasError(Exception):
    pass


# ---------------------------------------------------------------------------
# DNS sobre HTTPS: evita el bloqueo por DNS de algunos proveedores (el TLS sigue verificando el dominio)
# ---------------------------------------------------------------------------
_DNS: dict[str, str] = {}
_dns_lock = threading.Lock()
_getaddrinfo_original = socket.getaddrinfo


def _getaddrinfo(host, *args, **kwargs):
    ip = _DNS.get(host) if isinstance(host, str) else None
    return _getaddrinfo_original(ip or host, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo


def _resolver_doh(host: str) -> str | None:
    try:
        r = requests.get("https://cloudflare-dns.com/dns-query", params={"name": host, "type": "A"},
                         headers={"Accept": "application/dns-json"}, timeout=8)
        for ans in r.json().get("Answer", []):
            if ans.get("type") == 1 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ans.get("data", "")):
                return ans["data"]
    except (requests.RequestException, ValueError):
        pass
    return None


def _preparar_dns(host: str) -> None:
    if not load_settings()["literatura"].get("annas_doh", True) or host in _DNS:
        return
    try:
        _getaddrinfo_original(host, 443)
        return  # el DNS del sistema resuelve: no hace falta
    except OSError:
        pass
    ip = _resolver_doh(host)
    if ip:
        with _dns_lock:
            _DNS[host] = ip


def _sesion(forzar: str | None = None) -> requests.Session:
    from .literature import sesion
    return sesion("annas", forzar)


def _dominios() -> list[str]:
    s = load_settings()["literatura"]
    doms = [d.strip().rstrip("/") for d in (s.get("annas_dominios") or []) if d and d.strip()]
    return [d if d.startswith("http") else "https://" + d for d in doms]


def describir_respuesta(r: requests.Response) -> str:
    """Qué hay detrás de una respuesta fallida: reto anti-robots, bloqueo judicial, dominio aparcado…"""
    texto = (r.text or "")[:8000].lower()  # sin filtrar por Content-Type: un reto puede llegar sin cabecera text/*
    titulo = re.search(r"<title>([^<]{0,80})", texto)
    titulo = titulo.group(1).strip() if titulo else ""
    if "forsale" in texto or "domain is for sale" in texto:
        return "dominio aparcado (ya no es Anna's Archive)"
    if "just a moment" in texto or "cf-chl" in texto or "challenge-platform" in texto:
        return "reto anti-robots de Cloudflare"
    if "ddos-guard" in texto:
        return "DDoS-Guard"
    if "seized" in texto or "court order" in texto or "injunction" in texto or "blocked" in texto:
        return "bloqueado por orden judicial o del proveedor" + (f" («{titulo}»)" if titulo else "")
    return f"HTTP {r.status_code}" + (f" «{titulo}»" if titulo else "")


def _get(ruta: str, params: dict | None = None, timeout: int = 30) -> tuple[requests.Response, str]:
    errores = []
    rutas = [None] + (["directo"] if load_settings()["literatura"].get("tunel", "directo") != "directo" else [])
    for forzar in rutas:
        for base in _dominios():
            host = urllib.parse.urlsplit(base).hostname or ""
            if forzar == "directo" or load_settings()["literatura"].get("tunel", "directo") == "directo":
                _preparar_dns(host)
            etiqueta = host + (" (directo)" if forzar == "directo" else "")
            try:
                r = _sesion(forzar).get(base + ruta, params=params, timeout=timeout)
            except requests.RequestException as e:
                errores.append(f"{etiqueta}: sin conexión ({type(e).__name__})")
                continue
            texto = (r.text or "")[:5000].lower()
            if r.status_code == 200 and "forsale" not in texto and "domain is for sale" not in texto:
                return r, base
            errores.append(f"{etiqueta}: {describir_respuesta(r)}")
    # Retos anti-robots (DDoS-Guard / Cloudflare) o conexión cortada para Python: un navegador real
    # (WebView2, con su propia pila de red y DNS seguro) suele superarlos
    retados = [b for b in _dominios() if any(urllib.parse.urlsplit(b).hostname in e
                                             and ("DDoS-Guard" in e or "Cloudflare" in e or "sin conexión" in e)
                                             for e in errores)]
    from . import navegador
    if retados and navegador.disponible():
        consulta = ("?" + urllib.parse.urlencode(params, doseq=True)) if params else ""
        for base in retados:
            r = navegador.obtener_texto(base, base + ruta + consulta)
            if r and r[0] == 200:
                return _RespuestaNavegador(r[1], base + ruta), base
            errores.append(f"{urllib.parse.urlsplit(base).hostname}: el navegador integrado tampoco superó la verificación")
    elif retados:
        errores.append("abre la app con su ventana (no en el navegador) para superar la verificación automáticamente")
    raise AnnasError("Ningún dominio de Anna's Archive respondió (" + "; ".join(errores) + "). "
                     "Revisa la lista de dominios o ejecuta Ajustes → Diagnóstico.")


class _RespuestaNavegador:
    """Respuesta obtenida dentro de la ventana verificada (misma interfaz mínima que requests.Response)."""

    def __init__(self, texto: str, url: str):
        self.text, self.url, self.status_code = texto, url, 200
        self.headers = {"Content-Type": "text/html"}

    def json(self):
        import json
        return json.loads(self.text)


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def _texto_principal(td) -> str:
    """Texto de la celda sin las líneas «adicionales» (span.block)."""
    if td is None:
        return ""
    span = td.find("span", recursive=True)
    nodo = span if span else td
    partes = []
    for hijo in nodo.children:
        if getattr(hijo, "name", None) == "span" and "block" in (hijo.get("class") or []):
            continue
        partes.append(hijo.get_text(" ") if hasattr(hijo, "get_text") else str(hijo))
    return " ".join("".join(partes).split())


def parsear_tabla(html: str, base: str = "") -> list[dict]:
    html = html.replace("<!--", "").replace("-->", "")  # resultados de carga diferida
    sopa = BeautifulSoup(html, "html.parser")
    out, vistos = [], set()
    for tr in sopa.select("table tr"):
        enlace = tr.find("a", href=MD5_RE)
        if not enlace:
            continue
        md5 = MD5_RE.search(enlace["href"]).group(1)
        if md5 in vistos:
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 11:
            continue
        valores = {COLUMNAS[i]: _texto_principal(tds[i]) for i in range(1, min(len(tds), len(COLUMNAS)))}
        img = tds[0].find("img")
        titulo = valores.get("titulo") or valores.get("archivo") or md5
        autores = [a.strip() for a in re.split(r";|&|\band\b|, (?=[A-ZÁÉÍÓÚÑ][^,]{1,40}(?:,|$))", valores.get("autor", "")) if a.strip()][:8]
        ext = (valores.get("extension") or "").lower().strip(".")
        vistos.add(md5)
        out.append({
            "md5": md5, "titulo": titulo[:500], "autor": valores.get("autor", "")[:400], "autores": autores,
            "editorial": valores.get("editorial", "")[:200], "anio": valores.get("anio", "")[:10],
            "idioma": valores.get("idiomas", "")[:60], "tipo": valores.get("tipo", "")[:60],
            "extension": ext[:10], "tamano": valores.get("tamano", "")[:20], "fuentes": valores.get("fuentes", "")[:120],
            "portada": img.get("src") if img else None, "pagina_url": (base + "/md5/" + md5) if base else None,
        })
    if not out:  # vista de tarjetas (si el sitio ignoró display=table)
        for a in sopa.find_all("a", href=MD5_RE):
            md5 = MD5_RE.search(a["href"]).group(1)
            h3 = a.find("h3")
            if md5 in vistos or not h3:
                continue
            vistos.add(md5)
            fila = a.find("div", class_=re.compile("text-gray-500"))
            meta = fila.get_text(" ", strip=True) if fila else ""
            ext = next((p for p in re.split(r"[,·\s]+", meta.lower()) if p in {"pdf", "epub", "mobi", "djvu", "fb2", "azw3", "cbz", "cbr", "txt", "zip", "rar"}), "")
            autor = a.find("div", class_=re.compile("italic"))
            img = a.find("img")
            out.append({"md5": md5, "titulo": h3.get_text(" ", strip=True)[:500],
                        "autor": autor.get_text(" ", strip=True)[:400] if autor else "",
                        "autores": [autor.get_text(" ", strip=True)] if autor else [], "editorial": "", "anio": "",
                        "idioma": "", "tipo": "", "extension": ext, "tamano": meta[:60], "fuentes": "",
                        "portada": img.get("src") if img else None, "pagina_url": (base + "/md5/" + md5) if base else None})
    return out


def buscar(q: str, modo: str = "todo", tipos: list[str] | None = None, extension: str = "", idioma: str = "",
           orden: str = "relevancia", pagina: int = 1) -> dict:
    q = (q or "").strip()
    if len(q) < 2:
        raise AnnasError("Escribe al menos 2 caracteres.")
    params: list[tuple[str, str]] = [("q", q), ("display", "table"), ("page", str(max(1, min(int(pagina), 100))))]
    for t in tipos or []:
        if t in TIPOS:
            params.append(("content", TIPOS[t]))
    if extension:
        params.append(("ext", extension.lower().strip(".")))
    if idioma:
        params.append(("lang", idioma.lower()[:5]))
    if ORDEN.get(orden):
        params.append(("sort", ORDEN[orden]))
    r, base = _get("/search", params=dict(params) if len({k for k, _ in params}) == len(params) else params)
    res = parsear_tabla(r.text, base)
    if idioma:  # el sitio ya filtra; se refuerza con la columna de idiomas («Spanish [es]»)
        cod = idioma.lower()[:5]
        res = [x for x in res if not x["idioma"] or f"[{cod}]" in x["idioma"].lower() or cod in x["idioma"].lower()]
    # El sitio no tiene búsqueda por campo: se afina en el cliente
    claves = [w.lower() for w in re.findall(r"\w{2,}", q)]
    if modo == "autor" and claves:
        res = [x for x in res if all(k in x["autor"].lower() for k in claves)] or res
    elif modo == "titulo" and claves:
        res = [x for x in res if all(k in x["titulo"].lower() for k in claves)] or res
    return {"resultados": res, "pagina": pagina, "hay_mas": len(res) >= 50, "dominio": base}


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def enlace_descarga(item: dict) -> tuple[str | None, str]:
    """Devuelve (url_directa, vía). Primero la API de miembros; si no hay clave, LibGen por md5."""
    md5 = (item.get("md5") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise AnnasError("md5 no válido.")
    clave = load_settings()["literatura"].get("annas_clave", "")
    if clave:
        try:
            r, base = _get("/dyn/api/fast_download.json", params={"md5": md5, "key": clave}, timeout=40)
            url = r.json().get("download_url")
            if url:
                return url, f"descarga rápida de miembro ({urllib.parse.urlsplit(base).hostname})"
        except (AnnasError, ValueError):
            pass
    from . import libgen
    espejo = (load_settings()["literatura"].get("libgen_espejo") or "li").lstrip(".")
    libro = {"md5": md5, "titulo": item.get("titulo"), "autor": item.get("autor"), "extension": item.get("extension"),
             "espejos": [f"https://libgen.{espejo}/ads.php?md5={md5}"]}
    try:
        return libgen.resolver_enlace(libro), f"LibGen por md5 (libgen.{espejo})"
    except libgen.LibgenError as e:
        raise AnnasError("Sin clave de miembro y LibGen no tiene este md5 (" + str(e)[:120] + "). "
                         "Abre la ficha en Anna's Archive para ver otras descargas.") from None

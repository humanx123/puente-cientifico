"""Library Genesis mediante libgen-api-enhanced (https://github.com/onurhanak/libgen-api-enhanced).

Búsqueda por todo / título / autor en los temas de LibGen, filtros (extensión, idioma, año),
resolución del enlace directo y descarga a la biblioteca. Los libros EPUB, MOBI, FB2, CBZ y XPS
se convierten a PDF con PyMuPDF para poder leerlos, anotarlos y traducirlos; otros formatos
(DjVu, AZW3…) se guardan en la carpeta de libros y se abren con el programa de Windows.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import urllib.parse
import uuid
from pathlib import Path

from libgen_api_enhanced import LibgenSearch, SearchTopic
from libgen_api_enhanced.book import Book

from .config import DATA, load_settings

LIBROS_DIR = DATA / "libros"
LIBROS_DIR.mkdir(parents=True, exist_ok=True)
MAX_LIBRO = 400 * 1024 * 1024
TEMAS = {
    "libros": SearchTopic.LIBGEN, "ficcion": SearchTopic.FICTION, "comics": SearchTopic.COMICS,
    "revistas": SearchTopic.MAGAZINES, "normas": SearchTopic.STANDARDS,
}
# PyMuPDF puede abrir estos formatos y convertirlos a PDF
CONVERTIBLES = {"epub", "mobi", "fb2", "cbz", "xps", "oxps", "txt"}
_pool = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="libgen")


class LibgenError(Exception):
    pass


class _RequestsPorTunel:
    """libgen-api-enhanced llama a requests.get directamente; así pasa por el túnel y con tiempo límite."""

    def __getattr__(self, nombre):
        import requests
        return getattr(requests, nombre)

    def get(self, url, **kw):
        from .literature import sesion
        kw.setdefault("timeout", 40)
        return sesion().get(url, **kw)


class _ReSinBorrarAcentos:
    """search_request.py borra todo lo que no sea [A-Za-z0-9 ] de los títulos ("Célula" → "Clula").
    Anulamos solo ese patrón; el resto de expresiones del módulo funciona igual."""
    _PATRON = r"[^A-Za-z0-9 ]+"

    def __getattr__(self, nombre):
        return getattr(re, nombre)

    def sub(self, patron, repl, cadena, *a, **kw):
        if patron == self._PATRON and repl == "":
            return cadena
        return re.sub(patron, repl, cadena, *a, **kw)


def _instalar_shim() -> None:
    import libgen_api_enhanced.book as _b
    import libgen_api_enhanced.search_request as _sr
    _b.requests = _sr.requests = _RequestsPorTunel()
    _sr.re = _ReSinBorrarAcentos()


_instalar_shim()


def _cliente() -> LibgenSearch:
    s = load_settings()["literatura"]
    espejo = (s.get("libgen_espejo") or "li").strip().lstrip(".")
    return LibgenSearch(mirror=espejo, headers={"User-Agent": s.get("agente_usuario") or "PuenteCientifico/1.0"})


def _con_limite(fn, segundos: int, que: str):
    """libgen-api-enhanced no pone timeout a sus peticiones: las acotamos aquí."""
    fut = _pool.submit(fn)
    try:
        return fut.result(timeout=segundos)
    except cf.TimeoutError:
        raise LibgenError(f"LibGen tardó demasiado en {que}. Prueba otro espejo en Ajustes → Literatura.") from None
    except LibgenError:
        raise
    except Exception as e:
        raise LibgenError(f"Error de LibGen al {que}: {str(e)[:200]}") from None


def _libro(b: Book) -> dict | None:
    titulo = re.sub(r"\s+", " ", b.title or "").strip()
    if not titulo or not b.md5 or not any(b.mirrors or []):
        return None  # filas mal formadas (p. ej. la tabla de artículos del paquete)
    autores = [a.strip() for a in re.split(r";|,(?=\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s)", b.author or "") if a.strip()][:8]
    return {
        "id": b.id, "md5": b.md5.lower(), "titulo": titulo[:500], "autor": (b.author or "").strip()[:400],
        "autores": autores, "editorial": (b.publisher or "").strip()[:200], "anio": (b.year or "").strip()[:10],
        "idioma": (b.language or "").strip()[:40], "paginas": (b.pages or "").strip()[:20],
        "tamano": (b.size or "").strip()[:20], "extension": (b.extension or "").strip().lower()[:10],
        "espejos": [m for m in (b.mirrors or []) if m][:4], "portada": b.cover_url,
        "convertible": (b.extension or "").lower() in CONVERTIBLES | {"pdf"},
    }


IDIOMAS = {"es": "Spanish", "en": "English", "pt": "Portuguese", "fr": "French", "de": "German", "it": "Italian",
           "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ar": "Arabic", "ca": "Catalan", "nl": "Dutch"}
# Variantes con que LibGen escribe el idioma (a veces en el propio idioma)
VARIANTES = {"Spanish": ("spanish", "español", "espanol", "castellano"), "English": ("english",),
             "Portuguese": ("portuguese", "português", "portugues"), "French": ("french", "français", "francais"),
             "German": ("german", "deutsch"), "Italian": ("italian", "italiano"), "Russian": ("russian", "русский"),
             "Chinese": ("chinese", "中文"), "Japanese": ("japanese", "日本語"), "Arabic": ("arabic",),
             "Catalan": ("catalan", "català"), "Dutch": ("dutch", "nederlands")}


def buscar(q: str, modo: str = "todo", temas: list[str] | None = None, pagina: int = 1,
           extension: str = "", idioma: str = "", anio: str = "") -> dict:
    idioma = IDIOMAS.get((idioma or "").lower(), idioma or "")
    q = (q or "").strip()
    if len(q) < 3:
        raise LibgenError("LibGen necesita al menos 3 caracteres.")
    temas_ok = [TEMAS[t] for t in (temas or ["libros"]) if t in TEMAS] or [SearchTopic.LIBGEN]
    # El idioma se filtra después (LibGen lo escribe de varias formas: «Spanish», «Español»…)
    filtros = {k: v for k, v in (("extension", extension.lower()), ("year", anio)) if v}
    s = _cliente()
    pagina = max(1, min(int(pagina), 50))

    def consulta():
        if modo == "titulo":
            if filtros:
                return s.search_title_filtered(q, filtros, exact_match=False, search_in=temas_ok, page=pagina)
            return s.search_title(q, search_in=temas_ok, page=pagina)
        if modo == "autor":
            if filtros:
                return s.search_author_filtered(q, filtros, exact_match=False, search_in=temas_ok, page=pagina)
            return s.search_author(q, search_in=temas_ok, page=pagina)
        if filtros:
            return s.search_default_filtered(q, filtros, exact_match=False, search_in=temas_ok, page=pagina)
        return s.search_default(q, search_in=temas_ok, page=pagina)

    crudos = _con_limite(consulta, 45, "buscar")
    libros, vistos = [], set()
    variantes = VARIANTES.get(idioma, (idioma.lower(),)) if idioma else ()
    for b in crudos:
        l = _libro(b)
        if l and variantes and not any(v in l["idioma"].lower() for v in variantes):
            continue
        if l and l["md5"] not in vistos:
            vistos.add(l["md5"])
            libros.append(l)
    return {"libros": libros, "pagina": pagina, "hay_mas": len(crudos) >= 25}


def resolver_enlace(libro: dict) -> str:
    espejos = [m for m in libro.get("espejos", []) if isinstance(m, str) and m.startswith("http")]
    md5 = (libro.get("md5") or "").lower()
    if not espejos or not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise LibgenError("El resultado de LibGen no tiene espejos de descarga válidos.")
    ultimo = None
    for i, espejo in enumerate(espejos):
        b = Book(libro.get("id"), libro.get("titulo"), libro.get("autor"), "", "", "", "", "",
                 libro.get("extension"), md5, [espejo], None, "", "")
        try:
            _con_limite(lambda: b.resolve_direct_download_link(
                headers={"User-Agent": load_settings()["literatura"].get("agente_usuario")}), 40, "resolver el enlace")
            if b.resolved_download_link:
                return b.resolved_download_link
        except LibgenError as e:
            ultimo = e
    raise ultimo or LibgenError("Ningún espejo de LibGen entregó un enlace directo.")


def nombre_archivo(libro: dict) -> str:
    base = f"{libro.get('autores', [''])[0] if libro.get('autores') else ''} - {libro.get('titulo', 'libro')}".strip(" -")
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", base)
    base = " ".join(base.split())[:140] or "libro"
    ext = re.sub(r"[^a-z0-9]", "", (libro.get("extension") or "bin").lower())[:8] or "bin"
    return f"{base}.{ext}"


def destino_temporal(libro: dict) -> Path:
    ext = re.sub(r"[^a-z0-9]", "", (libro.get("extension") or "bin").lower())[:8] or "bin"
    return LIBROS_DIR / f".descarga-{uuid.uuid4().hex}.{ext}"


def dominio(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""

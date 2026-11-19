"""Resolución inteligente de un DOI a un PDF descargable.

Orden (de lo más fiable a lo más bloqueado):
1. Repositorios abiertos por prefijo del DOI: Figshare, Zenodo, arXiv, bioRxiv/medRxiv.
   Figshare y Zenodo detectan el material suplementario («IsSupplementTo») y saltan al artículo principal.
2. Copias abiertas: OpenAlex (todas sus ubicaciones), Unpaywall (si hay correo), Semantic Scholar y Europe PMC.
3. La página del DOI: enlace del PDF declarado por la revista (meta citation_pdf_url).
4. Anna's Archive y LibGen por DOI y por título (md5 → enlace directo).
5. Sci-Hub (rotación de espejos, lógica de SciHubEVA).
Si una fuente responde con verificación anti-robots (403 / «Just a moment»), se ofrece la ventana de
verificación integrada (navegador.py), que usa un Edge real para superarla.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

import requests

from .config import load_settings


@dataclass
class Candidato:
    url: str
    fuente: str
    pagina: str | None = None  # página HTML de origen (para la ventana de verificación)
    nota: str = ""


@dataclass
class Resolucion:
    doi: str
    candidatos: list[Candidato] = field(default_factory=list)
    doi_principal: str | None = None  # si el DOI era material suplementario
    suplemento: list[dict] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def _s():
    from .literature import sesion
    return sesion()


def _json(url: str, params: dict | None = None, timeout: int = 20):
    try:
        r = _s().get(url, params=params, timeout=timeout, headers={"Accept": "application/json"})
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. Repositorios por prefijo
# ---------------------------------------------------------------------------
def _figshare(doi: str, res: Resolucion) -> None:
    m = re.match(r"10\.6084/m9\.figshare\.(\d+)", doi)
    if not m:
        return
    d = _json(f"https://api.figshare.com/v2/articles/{m.group(1)}")
    if not d:
        return
    principal = d.get("resource_doi") or next((x.get("identifier") for x in d.get("related_materials") or []
                                                 if x.get("relation") == "IsSupplementTo"), None)
    archivos = d.get("files") or []
    pdfs = [f for f in archivos if (f.get("name") or "").lower().endswith(".pdf")]
    if principal and not pdfs:
        res.doi_principal = principal.lower()
        res.suplemento = [{"nombre": f.get("name"), "url": f.get("download_url"), "mb": round((f.get("size") or 0) / 1048576, 2)} for f in archivos]
        res.log.append(f"Figshare: este DOI es material suplementario ({', '.join(f['nombre'] for f in res.suplemento[:3])}). "
                       f"Artículo principal: {principal}")
    for f in pdfs:
        res.candidatos.append(Candidato(f["download_url"], "Figshare"))


def _zenodo(doi: str, res: Resolucion) -> None:
    m = re.match(r"10\.5281/zenodo\.(\d+)", doi)
    if not m:
        return
    d = _json(f"https://zenodo.org/api/records/{m.group(1)}")
    if not d:
        return
    for f in d.get("files") or []:
        nombre = f.get("key") or f.get("filename") or ""
        enlace = (f.get("links") or {}).get("self") or (f.get("links") or {}).get("download")
        if nombre.lower().endswith(".pdf") and enlace:
            res.candidatos.append(Candidato(enlace, "Zenodo"))
    rel = next((x.get("identifier") for x in (d.get("metadata") or {}).get("related_identifiers") or []
                if x.get("relation") in ("isSupplementTo", "isPartOf") and str(x.get("identifier", "")).startswith("10.")), None)
    if rel and not res.candidatos:
        res.doi_principal = rel.lower()
        res.log.append(f"Zenodo: material relacionado con el artículo {rel}")


def _arxiv(doi: str, res: Resolucion) -> None:
    m = re.match(r"10\.48550/arxiv\.(.+)", doi, re.I)
    if m:
        res.candidatos.append(Candidato(f"https://arxiv.org/pdf/{m.group(1)}", "arXiv"))


def _biorxiv(doi: str, res: Resolucion) -> None:
    if not doi.startswith("10.1101/"):
        return
    for servidor in ("biorxiv", "medrxiv"):
        d = _json(f"https://api.biorxiv.org/details/{servidor}/{doi}")
        coleccion = (d or {}).get("collection") or []
        if coleccion:
            v = coleccion[-1].get("version") or 1
            dominio = "www.biorxiv.org" if servidor == "biorxiv" else "www.medrxiv.org"
            pag = f"https://{dominio}/content/{doi}v{v}"
            res.candidatos.append(Candidato(pag + ".full.pdf", servidor, pagina=pag))
            return


# ---------------------------------------------------------------------------
# 2. Copias abiertas
# ---------------------------------------------------------------------------
def _openalex(doi: str, res: Resolucion) -> None:
    from .literature import OPENALEX, LitError, _oa_get
    try:
        r = _oa_get(f"{OPENALEX}/https://doi.org/{urllib.parse.quote(doi, safe='/')}", timeout=20)
        d = r.json() if r.status_code == 200 else None
    except (LitError, ValueError):
        d = None
    if not d:
        return
    vistos = {c.url for c in res.candidatos}
    for loc in [d.get("best_oa_location")] + (d.get("locations") or []):
        if isinstance(loc, dict) and loc.get("is_oa") and loc.get("pdf_url") and loc["pdf_url"] not in vistos:
            vistos.add(loc["pdf_url"])
            fuente = ((loc.get("source") or {}).get("display_name") or "copia abierta")[:60]
            res.candidatos.append(Candidato(loc["pdf_url"], f"OpenAlex · {fuente}", pagina=loc.get("landing_page_url")))


def _unpaywall(doi: str, res: Resolucion) -> None:
    correo = load_settings()["literatura"].get("openalex_correo")
    if not correo:
        return
    d = _json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}", {"email": correo})
    vistos = {c.url for c in res.candidatos}
    for loc in (d or {}).get("oa_locations") or []:
        u = loc.get("url_for_pdf")
        if u and u not in vistos:
            vistos.add(u)
            res.candidatos.append(Candidato(u, f"Unpaywall · {loc.get('host_type', '')}", pagina=loc.get("url_for_landing_page")))


def _semantic_scholar(doi: str, res: Resolucion) -> None:
    d = _json(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='/')}",
              {"fields": "openAccessPdf,externalIds"})
    u = ((d or {}).get("openAccessPdf") or {}).get("url")
    if u and u not in {c.url for c in res.candidatos}:
        res.candidatos.append(Candidato(u, "Semantic Scholar"))
    pmc = ((d or {}).get("externalIds") or {}).get("PubMedCentral")
    if pmc:
        res.candidatos.append(Candidato(f"https://europepmc.org/articles/PMC{pmc}?pdf=render", "Europe PMC"))


def _pagina_doi(doi: str, res: Resolucion) -> None:
    """Meta citation_pdf_url de la página de la revista (muchas editoriales la publican)."""
    try:
        r = _s().get(f"https://doi.org/{urllib.parse.quote(doi, safe='/')}", timeout=25, allow_redirects=True)
    except requests.RequestException:
        return
    if r.status_code == 403 or "just a moment" in r.text[:3000].lower():
        res.log.append(f"La revista ({urllib.parse.urlsplit(r.url).hostname}) bloquea programas: se puede usar la ventana de verificación.")
        res.candidatos.append(Candidato(r.url, "página de la revista (verificación)", pagina=r.url, nota="verificar"))
        return
    if r.status_code != 200 or "html" not in r.headers.get("Content-Type", ""):
        return
    for m in re.finditer(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', r.text, re.I):
        u = urllib.parse.urljoin(r.url, m.group(1))
        if u not in {c.url for c in res.candidatos}:
            res.candidatos.append(Candidato(u, "PDF declarado por la revista", pagina=r.url))


def resolver(doi: str) -> Resolucion:
    res = Resolucion(doi=doi)
    for fn in (_figshare, _zenodo, _arxiv, _biorxiv):
        fn(doi, res)
    objetivo = res.doi_principal or doi
    if res.doi_principal:
        for fn in (_arxiv, _biorxiv):
            fn(objetivo, res)
    for fn in (_openalex, _unpaywall, _semantic_scholar, _pagina_doi):
        try:
            fn(objetivo, res)
        except Exception as e:  # una fuente caída nunca detiene la cadena
            res.log.append(f"{fn.__name__.strip('_')}: {str(e)[:80]}")
    return res


def es_bloqueo(texto_o_html: str, codigo: int | None = None) -> bool:
    t = (texto_o_html or "")[:4000].lower()
    return codigo == 403 or any(x in t for x in ("just a moment", "cf-chl", "attention required", "captcha",
                                                 "altcha", "verify you are human", "ddos-guard", "challenge-platform"))

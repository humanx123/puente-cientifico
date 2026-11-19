"""Biblioteca de documentos PDF (inspirada en PageBridge): importar, organizar,
renderizar, buscar, anotar y exportar."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from . import db
from .config import CACHE_DIR, EXPORT_DIR, LIBRARY_DIR, TRANSLATED_DIR

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
RENDER_DIR = CACHE_DIR / "render"
RENDER_DIR.mkdir(parents=True, exist_ok=True)
_render_lock = threading.Lock()


class LibraryError(Exception):
    pass


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _guess_title(doc: fitz.Document, fallback: str) -> str:
    meta = doc.metadata or {}
    title = (meta.get("title") or "").strip()
    bad = ("untitled", "microsoft word", ".doc", ".pdf", ".tex", "title")
    palabras = re.findall(r"[^\W\d_]{2,}", title)
    parece_archivo = re.search(r"\d+\.\.\d+|^\S+$|_", title) is not None
    if title and len(palabras) >= 3 and not parece_archivo and not any(b in title.lower() for b in bad):
        return title[:300]
    # Texto con la fuente más grande en la primera página
    try:
        page = doc[0]
        best, best_size = "", 0.0
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                size = max((s["size"] for s in line["spans"]), default=0)
                if len(text) > 8 and size > best_size + 0.5:
                    best, best_size = text, size
                elif len(text) > 3 and abs(size - best_size) <= 0.5 and best and len(best) < 200:
                    best = best + " " + text
        if best:
            return best[:300]
    except Exception:
        pass
    return fallback[:300]


def _guess_doi(doc: fitz.Document) -> str | None:
    meta = doc.metadata or {}
    for value in (meta.get("subject", ""), meta.get("keywords", "")):
        m = DOI_RE.search(value or "")
        if m:
            return m.group(1).rstrip(".,;)").lower()
    for i in range(min(2, doc.page_count)):
        m = DOI_RE.search(doc[i].get_text("text"))
        if m:
            return m.group(1).rstrip(".,;)").lower()
    return None


def _index_text(doc_id: int, pdf: fitz.Document, tipo: str = "original") -> None:
    with db.tx() as c:
        c.execute("DELETE FROM texto_fts WHERE documento_id=? AND tipo=?", (doc_id, tipo))
        for i, page in enumerate(pdf):
            text = page.get_text("text")
            if text.strip():
                c.execute(
                    "INSERT INTO texto_fts(documento_id, pagina, tipo, contenido) VALUES (?,?,?,?)",
                    (doc_id, i + 1, tipo, text),
                )


EBOOKS = {".epub", ".mobi", ".fb2", ".cbz", ".xps", ".oxps"}


def convertir_a_pdf(src: Path) -> Path:
    """EPUB, MOBI, FB2, CBZ y XPS → PDF (PyMuPDF maqueta el libro en páginas)."""
    try:
        doc = fitz.open(src, filetype=src.suffix.lstrip(".").lower())
        datos = doc.convert_to_pdf()
        doc.close()
    except Exception as e:
        raise LibraryError(f"No se pudo convertir {src.suffix} a PDF: {e}") from None
    out = CACHE_DIR / f"convertido-{hashlib.sha1(str(src).encode()).hexdigest()[:12]}.pdf"
    out.write_bytes(datos)
    return out


def import_pdf(src: Path, *, title: str | None = None, authors: str = "", year: int | None = None,
               doi: str | None = None, origen: str = "importado", carpeta_id: int | None = None) -> dict:
    src = Path(src)
    if not src.exists():
        raise LibraryError(f"No existe el archivo: {src}")
    if src.suffix.lower() in EBOOKS:
        convertido = convertir_a_pdf(src)
        try:
            return import_pdf(convertido, title=title or src.stem, authors=authors, year=year, doi=doi,
                              origen=origen, carpeta_id=carpeta_id)
        finally:
            convertido.unlink(missing_ok=True)
    with open(src, "rb") as f:
        head = f.read(1024)
    if b"%PDF-" not in head:
        raise LibraryError("El archivo no es un PDF ni un libro electrónico compatible (EPUB, MOBI, FB2, CBZ, XPS).")
    sha = _sha256(src)
    existing = db.row("SELECT * FROM documentos WHERE sha256=?", (sha,))
    if existing:
        if existing.get("papelera"):
            with db.tx() as c:
                c.execute("UPDATE documentos SET papelera=NULL WHERE id=?", (existing["id"],))
            existing["papelera"] = None
        existing["duplicado"] = True
        return existing
    try:
        pdf = fitz.open(src)
    except Exception as e:
        raise LibraryError(f"No se pudo abrir el PDF: {e}") from None
    if pdf.needs_pass:
        raise LibraryError("El PDF está protegido con contraseña.")
    dest = LIBRARY_DIR / f"{sha[:20]}.pdf"
    if not dest.exists():
        shutil.copyfile(src, dest)
    title = (title or "").strip() or _guess_title(pdf, src.stem)
    doi = (doi or "").strip().lower() or _guess_doi(pdf)
    if not year:
        m = re.match(r"D:(\d{4})", (pdf.metadata or {}).get("creationDate", "") or "")
        year = int(m.group(1)) if m else None
    if not authors:
        authors = ((pdf.metadata or {}).get("author") or "").strip()
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO documentos(titulo, autores, anio, doi, archivo, sha256, paginas, tamano, carpeta_id, origen)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, authors, year, doi, str(dest), sha, pdf.page_count, dest.stat().st_size, carpeta_id, origen),
        )
        doc_id = cur.lastrowid
    _index_text(doc_id, pdf)
    pdf.close()
    return get(doc_id)


# ---------------------------------------------------------------------------
# Consulta y organización
# ---------------------------------------------------------------------------
def get(doc_id: int) -> dict:
    d = db.row(
        "SELECT d.*, c.nombre AS carpeta FROM documentos d LEFT JOIN carpetas c ON c.id=d.carpeta_id WHERE d.id=?",
        (doc_id,),
    )
    if not d:
        raise LibraryError("Documento no encontrado.")
    d["traducciones"] = db.rows(
        "SELECT id, origen, destino, estado, actualizada FROM traducciones WHERE documento_id=?", (doc_id,)
    )
    d["notas"] = db.row("SELECT COUNT(*) AS n FROM notas WHERE documento_id=?", (doc_id,))["n"]
    return d


def listar(vista: str = "todos", carpeta_id: int | None = None, q: str = "", orden: str = "agregado") -> list[dict]:
    where, params = [], []
    if vista == "papelera":
        where.append("d.papelera IS NOT NULL")
    else:
        where.append("d.papelera IS NULL")
        if vista == "favoritos":
            where.append("d.favorito=1")
        elif vista == "recientes":
            where.append("d.abierto IS NOT NULL")
        elif vista == "traducidos":
            where.append("EXISTS (SELECT 1 FROM traducciones t WHERE t.documento_id=d.id)")
    if carpeta_id:
        where.append("d.carpeta_id=?")
        params.append(carpeta_id)
    if q:
        where.append("(d.titulo LIKE ? OR d.autores LIKE ? OR d.doi LIKE ?)")
        params += [f"%{q}%"] * 3
    order = {
        "agregado": "d.agregado DESC",
        "titulo": "d.titulo COLLATE NOCASE ASC",
        "abierto": "d.abierto DESC",
        "anio": "d.anio DESC",
        "paginas": "d.paginas DESC",
    }.get(orden, "d.agregado DESC")
    if vista == "recientes":
        order = "d.abierto DESC"
    sql = (
        "SELECT d.*, c.nombre AS carpeta,"
        " (SELECT COUNT(*) FROM traducciones t WHERE t.documento_id=d.id) AS n_traducciones,"
        " (SELECT COUNT(*) FROM notas n WHERE n.documento_id=d.id) AS n_notas"
        " FROM documentos d LEFT JOIN carpetas c ON c.id=d.carpeta_id"
        f" WHERE {' AND '.join(where)} ORDER BY {order}"
    )
    return db.rows(sql, params)


def actualizar(doc_id: int, campos: dict) -> dict:
    permitidos = {"titulo", "autores", "anio", "doi", "carpeta_id", "favorito", "pagina_actual"}
    sets = {k: v for k, v in campos.items() if k in permitidos}
    if sets:
        with db.tx() as c:
            c.execute(
                f"UPDATE documentos SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                (*sets.values(), doc_id),
            )
    return get(doc_id)


def marcar_abierto(doc_id: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE documentos SET abierto=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), doc_id))


def a_papelera(doc_id: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE documentos SET papelera=datetime('now','localtime') WHERE id=?", (doc_id,))


def restaurar(doc_id: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE documentos SET papelera=NULL WHERE id=?", (doc_id,))


def vaciar_papelera() -> int:
    docs = db.rows("SELECT id, archivo FROM documentos WHERE papelera IS NOT NULL")
    for d in docs:
        borrar_definitivo(d["id"])
    return len(docs)


def borrar_definitivo(doc_id: int) -> None:
    d = db.row("SELECT * FROM documentos WHERE id=?", (doc_id,))
    if not d:
        return
    trans = db.rows("SELECT archivo FROM traducciones WHERE documento_id=?", (doc_id,))
    with db.tx() as c:
        c.execute("DELETE FROM texto_fts WHERE documento_id=?", (doc_id,))
        c.execute("DELETE FROM documentos WHERE id=?", (doc_id,))
    for p in [d["archivo"]] + [t["archivo"] for t in trans]:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    for p in RENDER_DIR.glob(f"{doc_id}_*"):
        p.unlink(missing_ok=True)


def carpetas() -> list[dict]:
    return db.rows(
        "SELECT c.*, (SELECT COUNT(*) FROM documentos d WHERE d.carpeta_id=c.id AND d.papelera IS NULL) AS n"
        " FROM carpetas c ORDER BY nombre COLLATE NOCASE"
    )


def crear_carpeta(nombre: str) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise LibraryError("Escribe un nombre de carpeta.")
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO carpetas(nombre) VALUES (?)", (nombre,))
    return db.row("SELECT * FROM carpetas WHERE nombre=?", (nombre,))


def renombrar_carpeta(cid: int, nombre: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE carpetas SET nombre=? WHERE id=?", (nombre.strip(), cid))


def borrar_carpeta(cid: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE documentos SET carpeta_id=NULL WHERE carpeta_id=?", (cid,))
        c.execute("DELETE FROM carpetas WHERE id=?", (cid,))


def estadisticas() -> dict:
    return {
        "documentos": db.row("SELECT COUNT(*) n FROM documentos WHERE papelera IS NULL")["n"],
        "paginas": db.row("SELECT COALESCE(SUM(paginas),0) n FROM documentos WHERE papelera IS NULL")["n"],
        "traducciones": db.row("SELECT COUNT(*) n FROM traducciones")["n"],
        "notas": db.row("SELECT COUNT(*) n FROM notas")["n"],
        "favoritos": db.row("SELECT COUNT(*) n FROM documentos WHERE favorito=1 AND papelera IS NULL")["n"],
        "papelera": db.row("SELECT COUNT(*) n FROM documentos WHERE papelera IS NOT NULL")["n"],
    }


# ---------------------------------------------------------------------------
# Lectura y renderizado
# ---------------------------------------------------------------------------
def ruta_variante(doc_id: int, variante: str) -> Path:
    """variante = 'original' o 'es', 'en'... (idioma de una traducción existente)."""
    d = db.row("SELECT archivo FROM documentos WHERE id=?", (doc_id,))
    if not d:
        raise LibraryError("Documento no encontrado.")
    if variante in ("", "original"):
        return Path(d["archivo"])
    t = db.row("SELECT archivo FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, variante))
    if not t or not Path(t["archivo"]).exists():
        raise LibraryError("Aún no hay traducción en ese idioma.")
    return Path(t["archivo"])


def render(doc_id: int, pagina: int, zoom: float = 1.5, variante: str = "original") -> Path:
    zoom = max(0.15, min(4.0, round(zoom, 2)))
    src = ruta_variante(doc_id, variante)
    stamp = int(src.stat().st_mtime)
    out = RENDER_DIR / f"{doc_id}_{variante}_{pagina}_{zoom}_{stamp}.png"
    if out.exists():
        return out
    with _render_lock:
        pdf = fitz.open(src)
        try:
            if not 1 <= pagina <= pdf.page_count:
                raise LibraryError("Página fuera de rango.")
            pix = pdf[pagina - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(out)
        finally:
            pdf.close()
    return out


def info_paginas(doc_id: int) -> list[dict]:
    pdf = fitz.open(ruta_variante(doc_id, "original"))
    try:
        return [{"n": i + 1, "w": p.rect.width, "h": p.rect.height} for i, p in enumerate(pdf)]
    finally:
        pdf.close()


def indice(doc_id: int) -> list[dict]:
    pdf = fitz.open(ruta_variante(doc_id, "original"))
    try:
        return [{"nivel": lvl, "titulo": t, "pagina": p} for lvl, t, p in pdf.get_toc(simple=True)]
    finally:
        pdf.close()


def capa_texto(doc_id: int, pagina: int, variante: str = "original") -> dict:
    """Palabras con coordenadas normalizadas (0-1) para la capa de texto seleccionable."""
    pdf = fitz.open(ruta_variante(doc_id, variante))
    try:
        page = pdf[pagina - 1]
        W, H = page.rect.width, page.rect.height
        words = page.get_text("words")
        out = []
        for x0, y0, x1, y1, w, b, l, n in words:
            out.append([round(x0 / W, 5), round(y0 / H, 5), round(x1 / W, 5), round(y1 / H, 5), w, b, l])
        return {"w": W, "h": H, "palabras": out}
    finally:
        pdf.close()


def texto_pagina(doc_id: int, pagina: int, variante: str = "original") -> str:
    pdf = fitz.open(ruta_variante(doc_id, variante))
    try:
        return pdf[pagina - 1].get_text("text")
    finally:
        pdf.close()


def buscar_en_documento(doc_id: int, q: str, variante: str = "original") -> list[dict]:
    q = q.strip()
    if not q:
        return []
    pdf = fitz.open(ruta_variante(doc_id, variante))
    out = []
    try:
        for i, page in enumerate(pdf):
            W, H = page.rect.width, page.rect.height
            rects = page.search_for(q)
            if rects:
                text = page.get_text("text")
                idx = text.lower().find(q.lower())
                ctx = text[max(0, idx - 60): idx + len(q) + 60].replace("\n", " ") if idx >= 0 else ""
                out.append({
                    "pagina": i + 1,
                    "contexto": ctx,
                    "rects": [[r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H] for r in rects],
                })
    finally:
        pdf.close()
    return out


def rects_de_cita(doc_id: int, pagina: int, cita: str, variante: str = "original") -> list[list[float]]:
    if not cita.strip():
        return []
    pdf = fitz.open(ruta_variante(doc_id, variante))
    try:
        page = pdf[pagina - 1]
        W, H = page.rect.width, page.rect.height
        rects = page.search_for(cita.strip()[:400])
        return [[r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H] for r in rects]
    finally:
        pdf.close()


def busqueda_global(q: str, limite: int = 60) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    # Cada palabra como prefijo, entre comillas para evitar errores de sintaxis FTS
    terms = [t for t in re.findall(r"\w+", q, flags=re.UNICODE) if t]
    if not terms:
        return []
    match = " ".join('"' + t.replace('"', "") + '"*' for t in terms)
    try:
        res = db.rows(
            "SELECT f.documento_id, f.pagina, f.tipo, snippet(texto_fts, 3, '[[', ']]', ' … ', 18) AS fragmento,"
            " d.titulo FROM texto_fts f JOIN documentos d ON d.id=f.documento_id"
            " WHERE texto_fts MATCH ? AND d.papelera IS NULL ORDER BY rank LIMIT ?",
            (match, limite),
        )
    except Exception:
        return []
    return res


# ---------------------------------------------------------------------------
# Notas, resaltados y marcadores
# ---------------------------------------------------------------------------
def notas(doc_id: int) -> list[dict]:
    return db.rows("SELECT * FROM notas WHERE documento_id=? ORDER BY pagina, id", (doc_id,))


def crear_nota(doc_id: int, pagina: int, tipo: str, texto: str = "", cita: str = "", color: str = "#ffe600") -> dict:
    if tipo not in {"nota", "resaltado", "subrayado", "marcador", "asistente"}:
        raise LibraryError("Tipo de nota no válido.")
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO notas(documento_id, pagina, tipo, texto, cita, color) VALUES (?,?,?,?,?,?)",
            (doc_id, pagina, tipo, texto, cita, color),
        )
    return db.row("SELECT * FROM notas WHERE id=?", (cur.lastrowid,))


def editar_nota(nid: int, texto: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE notas SET texto=? WHERE id=?", (texto, nid))


def borrar_nota(nid: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM notas WHERE id=?", (nid,))


def _hex_rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (1, 0.9, 0)
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _nombre_seguro(texto: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", texto)
    s = " ".join(s.split())[:90].strip(". ")
    return s or "documento"


def exportar_anotado(doc_id: int) -> Path:
    d = get(doc_id)
    pdf = fitz.open(d["archivo"])
    for n in notas(doc_id):
        if not 1 <= n["pagina"] <= pdf.page_count:
            continue
        page = pdf[n["pagina"] - 1]
        if n["tipo"] in ("resaltado", "subrayado") and n["cita"]:
            quads = page.search_for(n["cita"][:400], quads=True)
            if quads:
                annot = page.add_highlight_annot(quads) if n["tipo"] == "resaltado" else page.add_underline_annot(quads)
                annot.set_colors(stroke=_hex_rgb(n["color"]))
                if n["texto"]:
                    annot.set_info(content=n["texto"])
                annot.update()
        elif n["tipo"] in ("nota", "asistente", "marcador"):
            annot = page.add_text_annot(fitz.Point(20, 20), (n["texto"] or n["cita"] or "Marcador")[:4000])
            annot.set_info(title="Puente Científico")
            annot.update()
    out = EXPORT_DIR / f"{_nombre_seguro(d['titulo'])} (anotado).pdf"
    pdf.save(out, garbage=3, deflate=True)
    pdf.close()
    return out


def exportar_markdown(doc_id: int) -> Path:
    d = get(doc_id)
    lines = [f"# {d['titulo']}", ""]
    if d.get("autores"):
        lines += [f"**Autores:** {d['autores']}", ""]
    if d.get("doi"):
        lines += [f"**DOI:** https://doi.org/{d['doi']}", ""]
    nombres = {"nota": "Nota", "resaltado": "Resaltado", "subrayado": "Subrayado", "marcador": "Marcador", "asistente": "Asistente IA"}
    for n in notas(doc_id):
        lines.append(f"## Página {n['pagina']} · {nombres.get(n['tipo'], n['tipo'])}")
        if n["cita"]:
            lines.append("> " + n["cita"].replace("\n", "\n> "))
        if n["texto"]:
            lines.append("")
            lines.append(n["texto"])
        lines.append("")
    out = EXPORT_DIR / f"{_nombre_seguro(d['titulo'])} (notas).md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def ruta_traducciones() -> Path:
    return TRANSLATED_DIR


def metadatos_json(doc_id: int) -> str:
    return json.dumps(get(doc_id), ensure_ascii=False)

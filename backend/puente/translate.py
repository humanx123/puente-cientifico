"""Traducción de PDF conservando la maquetación (equivalente ligero del "原页版式" de PageBridge).

Flujo:
1. Se extraen bloques de texto con sus coordenadas (PyMuPDF), uno por párrafo.
2. Se traducen por lotes con el modelo configurado, inyectando términos del glosario.
3. Se reconstruye el PDF: se borra solo el texto original de cada bloque (imágenes,
   líneas y fondos de color se conservan) y se escribe la traducción en el mismo
   recuadro, ajustando el tamaño de letra para que quepa.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import uuid
from pathlib import Path

import fitz

from . import db, glossary, library, llm
from .config import EXPORT_DIR, TRANSLATED_DIR, load_settings

IDIOMAS = {
    "es": "español", "en": "inglés", "pt": "portugués", "fr": "francés", "de": "alemán", "it": "italiano",
    "zh": "chino simplificado", "zh-TW": "chino tradicional", "ja": "japonés", "ko": "coreano", "ru": "ruso",
}

LOTE_MAX_SEG = 14
LOTE_MAX_CHARS = 3800

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


class TranslateError(Exception):
    pass


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def parse_rango(texto: str, total: int) -> list[int]:
    """'1-5, 8' -> [1,2,3,4,5,8]. Vacío o 'todo' -> todas las páginas."""
    texto = (texto or "").strip().lower()
    if not texto or texto in ("todo", "todas", "all", "*"):
        return list(range(1, total + 1))
    paginas: set[int] = set()
    for parte in re.split(r"[,;\s]+", texto):
        if not parte:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)?", parte)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else total
            if a > b:
                a, b = b, a
            paginas.update(range(max(1, a), min(total, b) + 1))
        elif parte.isdigit():
            n = int(parte)
            if 1 <= n <= total:
                paginas.add(n)
        else:
            raise TranslateError(f"Rango de páginas no válido: «{parte}». Usa por ejemplo 1-5, 8")
    if not paginas:
        raise TranslateError("El rango no contiene páginas del documento.")
    return sorted(paginas)


def _traducible(texto: str) -> bool:
    letras = sum(ch.isalpha() for ch in texto)
    if letras < 2:
        return False
    # Fórmulas y tablas puramente numéricas se dejan como están
    simbolos = sum(not ch.isalnum() and not ch.isspace() for ch in texto)
    return letras >= max(2, simbolos * 0.8)


def _unir_lineas(lineas: list[str]) -> str:
    out = ""
    for ln in lineas:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        elif out:
            out += " " + ln
        else:
            out = ln
    return out


def extraer_bloques(page: fitz.Page) -> list[dict]:
    bloques = []
    d = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_IMAGES)
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        lineas, tamanos, colores, negritas = [], [], [], []
        for line in b.get("lines", []):
            if line.get("dir", (1, 0))[0] < 0.9:  # texto girado: no se toca
                lineas = []
                break
            spans = line.get("spans", [])
            lineas.append("".join(s["text"] for s in spans))
            for s in spans:
                if s["text"].strip():
                    tamanos.append(s["size"])
                    colores.append(s.get("color", 0))
                    negritas.append(bool(s.get("flags", 0) & 16) or bool(re.search(r"bold|black|heavy|semibold", s.get("font", ""), re.I)))
        texto = _unir_lineas(lineas)
        if not texto or not tamanos:
            continue
        tamanos.sort()
        bloques.append({
            "bbox": list(b["bbox"]),
            "tam": tamanos[len(tamanos) // 2],
            "color": max(set(colores), key=colores.count),
            "negrita": sum(negritas) > len(negritas) / 2,
            "texto": texto,
            "traducible": _traducible(texto),
        })
    return bloques


# ---------------------------------------------------------------------------
# Registro de traducciones
# ---------------------------------------------------------------------------
def _registro(doc_id: int, origen: str, destino: str) -> dict:
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if t:
        if t["origen"] != origen:
            with db.tx() as c:
                c.execute("UPDATE traducciones SET origen=? WHERE id=?", (origen, t["id"]))
            t["origen"] = origen
        return t
    archivo = TRANSLATED_DIR / f"{doc_id}_{destino}.pdf"
    with db.tx() as c:
        c.execute(
            "INSERT INTO traducciones(documento_id, origen, destino, archivo) VALUES (?,?,?,?)",
            (doc_id, origen, destino, str(archivo)),
        )
    return db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))


def _asegurar_segmentos(trad: dict, pdf: fitz.Document, paginas: list[int]) -> None:
    existentes = {r["pagina"] for r in db.rows(
        "SELECT DISTINCT pagina FROM segmentos WHERE traduccion_id=?", (trad["id"],))}
    with db.tx() as c:
        for p in paginas:
            if p in existentes:
                continue
            for i, b in enumerate(extraer_bloques(pdf[p - 1])):
                x0, y0, x1, y1 = b["bbox"]
                c.execute(
                    "INSERT OR IGNORE INTO segmentos(traduccion_id, pagina, bloque, x0, y0, x1, y1, tam_fuente, color, negrita,"
                    " original, estado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (trad["id"], p, i, x0, y0, x1, y1, b["tam"], b["color"], int(b["negrita"]), b["texto"],
                     "pendiente" if b["traducible"] else "omitido"),
                )


# ---------------------------------------------------------------------------
# Llamadas al modelo
# ---------------------------------------------------------------------------
def _prompt_sistema(origen: str, destino: str, terminos: list[list[str]]) -> str:
    base = (
        f"Eres un traductor científico profesional. Traduce del {IDIOMAS.get(origen, origen)} al "
        f"{IDIOMAS.get(destino, destino)} con precisión técnica y estilo natural. "
        "Conserva números, unidades, fórmulas, símbolos, nombres propios, siglas de genes y proteínas, "
        "citas entre corchetes como [12] y direcciones web sin traducir. No añadas explicaciones. "
        "Recibirás un objeto JSON con la lista \"segmentos\". Responde SOLO con un objeto JSON "
        "{\"traducciones\": [...]} con exactamente el mismo número de elementos y en el mismo orden."
    )
    if terminos:
        base += "\nUsa obligatoriamente estas equivalencias de terminología:\n" + "\n".join(
            f"- {a} → {b}" for a, b in terminos)
    return base


def _parse_json_lista(texto: str, n: int) -> list[str] | None:
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    for candidato in (texto, texto[texto.find("{"): texto.rfind("}") + 1] if "{" in texto else "",
                      texto[texto.find("["): texto.rfind("]") + 1] if "[" in texto else ""):
        if not candidato:
            continue
        try:
            data = json.loads(candidato)
        except ValueError:
            continue
        if isinstance(data, dict):
            for k in ("traducciones", "translations", "segmentos", "result", "resultado"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if isinstance(data, list) and len(data) == n and all(isinstance(x, (str, int, float)) for x in data):
            return [str(x) for x in data]
    return None


_ECO_PROMPT = re.compile(r"traductor científico|Responde SOLO|equivalencias de terminolog|\"segmentos\"", re.I)


def _limpiar_salida(original: str, traducido: str) -> str:
    t = traducido.strip()
    t = re.sub(r"^(traducci[oó]n|translation)\s*:\s*", "", t, flags=re.I).strip()
    if t.startswith('"') and t.endswith('"') and not original.startswith('"'):
        t = t[1:-1].strip()
    if not t:
        raise TranslateError("El modelo devolvió una traducción vacía.")
    if _ECO_PROMPT.search(t):
        raise TranslateError("El modelo repitió las instrucciones en vez de traducir (prueba un modelo más capaz).")
    if len(t) > max(80, len(original) * 4):
        raise TranslateError("La respuesta del modelo es demasiado larga para este párrafo.")
    return t


def traducir_textos(textos: list[str], origen: str, destino: str, terminos_todos: list[list[str]],
                    cfg: dict | None = None) -> list[str]:
    cfg = cfg or llm.config_activa("traduccion")
    terminos = glossary.coincidencias(" ".join(textos), terminos_todos)
    sistema = _prompt_sistema(origen, destino, terminos)
    usuario = json.dumps({"segmentos": textos}, ensure_ascii=False)
    # ~0,45 tokens por carácter de salida (con margen para el JSON y para idiomas más largos)
    tope = int(sum(len(t) for t in textos) * 0.9) + 64 * len(textos) + 200
    for _ in range(2):
        resp = llm.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                        cfg, json_mode=True, max_tokens=tope)
        out = _parse_json_lista(resp, len(textos))
        if out:
            try:
                return [_limpiar_salida(o, t) for o, t in zip(textos, out)]
            except TranslateError:
                if len(textos) > 1:
                    raise
                break
    if len(textos) == 1:
        sistema_simple = (
            f"Traduce del {IDIOMAS.get(origen, origen)} al {IDIOMAS.get(destino, destino)} el texto del usuario. "
            "Responde únicamente con la traducción, sin comillas ni comentarios."
        )
        if terminos:
            sistema_simple += " Terminología obligatoria: " + "; ".join(f"{a} = {b}" for a, b in terminos)
        resp = llm.chat([{"role": "system", "content": sistema_simple}, {"role": "user", "content": textos[0]}], cfg,
                        max_tokens=int(len(textos[0]) * 0.9) + 120)
        return [_limpiar_salida(textos[0], resp)]
    raise TranslateError("El modelo no devolvió una lista válida.")


def _lotes(segs: list[dict]):
    lote, chars = [], 0
    for s in segs:
        if lote and (len(lote) >= LOTE_MAX_SEG or chars + len(s["original"]) > LOTE_MAX_CHARS):
            yield lote
            lote, chars = [], 0
        lote.append(s)
        chars += len(s["original"])
    if lote:
        yield lote


_contador_lock = threading.Lock()


def _traducir_segmentos(segs: list[dict], origen: str, destino: str, terminos: list[list[str]], cfg: dict,
                        job: dict | None = None) -> None:
    lotes = list(_lotes(segs))
    # Las APIs remotas aguantan peticiones simultáneas; Ollama local va en serie
    hilos = 1 if cfg.get("proveedor") == "ollama" else 3
    if hilos == 1 or len(lotes) == 1:
        for lote in lotes:
            _traducir_lote(lote, origen, destino, terminos, cfg, job)
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for f in [ex.submit(_traducir_lote, l, origen, destino, terminos, cfg, job) for l in lotes]:
            f.result()  # propaga errores fatales


def _traducir_lote(lote: list[dict], origen: str, destino: str, terminos: list[list[str]], cfg: dict,
                   job: dict | None = None) -> None:
    if job and job.get("cancelar"):
        return
    textos = [s["original"] for s in lote]
    try:
        res = traducir_textos(textos, origen, destino, terminos, cfg)
        with db.tx() as c:
            for s, t in zip(lote, res):
                c.execute("UPDATE segmentos SET traducido=?, estado='ok', error=NULL WHERE id=?", (t.strip(), s["id"]))
    except (llm.LLMError, TranslateError) as e:
        if isinstance(e, llm.LLMError) and e.fatal:
            raise
        # Reintento uno por uno para aislar el segmento problemático
        for s in lote:
            if job and job.get("cancelar"):
                return
            try:
                t = traducir_textos([s["original"]], origen, destino, terminos, cfg)[0]
                with db.tx() as c:
                    c.execute("UPDATE segmentos SET traducido=?, estado='ok', error=NULL WHERE id=?", (t.strip(), s["id"]))
            except (llm.LLMError, TranslateError) as e2:
                with db.tx() as c:
                    c.execute("UPDATE segmentos SET estado='error', error=? WHERE id=?", (str(e2)[:300], s["id"]))
                if job is not None:
                    with _contador_lock:
                        job["errores"] += 1
                        job["ultimo_error"] = str(e2)[:300]
                if isinstance(e2, llm.LLMError) and e2.fatal:
                    raise
    if job is not None:
        with _contador_lock:
            job["segmentos_hechos"] += len(lote)


# ---------------------------------------------------------------------------
# Reconstrucción del PDF traducido
# ---------------------------------------------------------------------------
def _rgb(color_int: int) -> str:
    return f"#{(color_int >> 16) & 255:02x}{(color_int >> 8) & 255:02x}{color_int & 255:02x}"


def construir_pdf(trad_id: int) -> Path:
    trad = db.row("SELECT * FROM traducciones WHERE id=?", (trad_id,))
    doc = db.row("SELECT archivo FROM documentos WHERE id=?", (trad["documento_id"],))
    pdf = fitz.open(doc["archivo"])
    segs = db.rows(
        "SELECT * FROM segmentos WHERE traduccion_id=? AND estado='ok' AND traducido IS NOT NULL ORDER BY pagina, bloque",
        (trad_id,),
    )
    por_pagina: dict[int, list[dict]] = {}
    for s in segs:
        por_pagina.setdefault(s["pagina"], []).append(s)
    for p, lista in por_pagina.items():
        page = pdf[p - 1]
        for s in lista:
            r = fitz.Rect(s["x0"], s["y0"], s["x1"], s["y1"])
            page.add_redact_annot(r, fill=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        for s in lista:
            r = fitz.Rect(s["x0"], s["y0"], s["x1"], s["y1"])
            # Margen extra a la derecha y abajo: el español suele ser ~20 % más largo
            r = fitz.Rect(r.x0, r.y0, min(page.rect.x1 - 4, r.x1 + 2), min(page.rect.y1 - 2, r.y1 + 2))
            peso = "bold" if s["negrita"] else "normal"
            css = (
                f"* {{font-family: sans-serif; font-size: {max(4.0, s['tam_fuente']):.1f}px; "
                f"color: {_rgb(s['color'] or 0)}; font-weight: {peso}; line-height: 1.12; margin: 0; padding: 0;}}"
            )
            contenido = "<p>" + html.escape(s["traducido"]) + "</p>"
            try:
                page.insert_htmlbox(r, contenido, css=css, scale_low=0)
            except Exception:
                page.insert_textbox(r, s["traducido"], fontsize=max(4, s["tam_fuente"] * 0.8), fontname="helv")
    destino = Path(trad["archivo"])
    tmp = destino.with_suffix(".tmp.pdf")
    pdf.save(tmp, garbage=3, deflate=True)
    pdf.close()
    tmp.replace(destino)
    # Índice de búsqueda del texto traducido
    with db.tx() as c:
        c.execute("DELETE FROM texto_fts WHERE documento_id=? AND tipo=?", (trad["documento_id"], "traduccion"))
        for p, lista in por_pagina.items():
            c.execute("INSERT INTO texto_fts(documento_id, pagina, tipo, contenido) VALUES (?,?,?,?)",
                      (trad["documento_id"], p, "traduccion", "\n".join(s["traducido"] for s in lista)))
        c.execute("UPDATE traducciones SET actualizada=datetime('now','localtime') WHERE id=?", (trad_id,))
    return destino


# ---------------------------------------------------------------------------
# Trabajos en segundo plano
# ---------------------------------------------------------------------------
def iniciar(doc_id: int, origen: str, destino: str, rango: str = "", glosarios: list[int] | None = None,
            reintentar_errores: bool = True) -> dict:
    if origen == destino:
        raise TranslateError("El idioma de origen y destino son iguales.")
    with _jobs_lock:
        for j in _jobs.values():
            if j["documento_id"] == doc_id and j["estado"] in ("en_curso", "preparando"):
                return j
    d = library.get(doc_id)
    pdf = fitz.open(d["archivo"])
    paginas = parse_rango(rango, pdf.page_count)
    pdf.close()
    s = load_settings()
    if glosarios is None:
        glosarios = s["traduccion"].get("glosarios_activos", [])
    job = {
        "id": uuid.uuid4().hex[:12], "documento_id": doc_id, "titulo": d["titulo"], "origen": origen, "destino": destino,
        "paginas": paginas, "pagina_actual": None, "paginas_hechas": 0, "segmentos_total": 0, "segmentos_hechos": 0,
        "errores": 0, "estado": "preparando", "mensaje": "Analizando páginas…", "ultimo_error": "",
        "inicio": time.time(), "fin": None, "cancelar": False,
    }
    with _jobs_lock:
        _jobs[job["id"]] = job
    threading.Thread(target=_ejecutar, args=(job, glosarios, reintentar_errores), daemon=True).start()
    return job


def _ejecutar(job: dict, glosarios: list[int], reintentar: bool) -> None:
    try:
        d = library.get(job["documento_id"])
        trad = _registro(job["documento_id"], job["origen"], job["destino"])
        pdf = fitz.open(d["archivo"])
        _asegurar_segmentos(trad, pdf, job["paginas"])
        pdf.close()
        estados = ("'pendiente','error'" if reintentar else "'pendiente'")
        marcadores = ",".join("?" * len(job["paginas"]))
        pendientes = db.rows(
            f"SELECT * FROM segmentos WHERE traduccion_id=? AND estado IN ({estados}) AND pagina IN ({marcadores})"
            " ORDER BY pagina, bloque",
            (trad["id"], *job["paginas"]),
        )
        job["segmentos_total"] = len(pendientes)
        terminos = glossary.terminos_activos(glosarios, job["origen"], job["destino"])
        cfg = llm.config_activa("traduccion")
        with db.tx() as c:
            c.execute("UPDATE traducciones SET estado='en_curso' WHERE id=?", (trad["id"],))
        job["estado"] = "en_curso"
        por_pagina: dict[int, list[dict]] = {}
        for s in pendientes:
            por_pagina.setdefault(s["pagina"], []).append(s)
        ultima_construccion = time.time()
        for p in job["paginas"]:
            if job["cancelar"]:
                break
            job["pagina_actual"] = p
            job["mensaje"] = f"Traduciendo página {p}…"
            segs = por_pagina.get(p, [])
            if segs:
                _traducir_segmentos(segs, job["origen"], job["destino"], terminos, cfg, job)
            job["paginas_hechas"] += 1
            if time.time() - ultima_construccion > 8:
                construir_pdf(trad["id"])
                ultima_construccion = time.time()
        job["mensaje"] = "Componiendo PDF traducido…"
        construir_pdf(trad["id"])
        restantes = db.row("SELECT COUNT(*) n FROM segmentos WHERE traduccion_id=? AND estado IN ('pendiente','error')",
                           (trad["id"],))["n"]
        with db.tx() as c:
            c.execute("UPDATE traducciones SET estado=? WHERE id=?",
                      ("completa" if restantes == 0 else "parcial", trad["id"]))
        if job["cancelar"]:
            job["estado"], job["mensaje"] = "cancelado", "Traducción detenida. Lo traducido se conserva."
        elif job["errores"]:
            job["estado"] = "con_errores"
            job["mensaje"] = f"Terminado con {job['errores']} segmentos sin traducir (puedes reintentarlos)."
        else:
            job["estado"], job["mensaje"] = "completado", "Traducción terminada."
    except Exception as e:  # el trabajo nunca debe tumbar el servidor
        job["estado"] = "error"
        job["mensaje"] = str(e)[:400]
        try:
            t = db.row("SELECT id FROM traducciones WHERE documento_id=? AND destino=?", (job["documento_id"], job["destino"]))
            if t:
                construir_pdf(t["id"])
        except Exception:
            pass
    finally:
        job["fin"] = time.time()


def trabajos() -> list[dict]:
    with _jobs_lock:
        return sorted((dict(j) for j in _jobs.values()), key=lambda j: -j["inicio"])


def trabajo(jid: str) -> dict:
    with _jobs_lock:
        if jid not in _jobs:
            raise TranslateError("Trabajo no encontrado.")
        return dict(_jobs[jid])


def cancelar(jid: str) -> None:
    with _jobs_lock:
        if jid in _jobs:
            _jobs[jid]["cancelar"] = True


# ---------------------------------------------------------------------------
# Segmentos: consulta, edición manual y reintentos
# ---------------------------------------------------------------------------
def segmentos(doc_id: int, destino: str, pagina: int) -> list[dict]:
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if not t:
        return []
    pdf = fitz.open(library.get(doc_id)["archivo"])
    W, H = pdf[pagina - 1].rect.width, pdf[pagina - 1].rect.height
    pdf.close()
    out = db.rows("SELECT id, pagina, bloque, x0, y0, x1, y1, original, traducido, estado, error FROM segmentos"
                  " WHERE traduccion_id=? AND pagina=? ORDER BY bloque", (t["id"], pagina))
    for s in out:
        s["rect"] = [s["x0"] / W, s["y0"] / H, s["x1"] / W, s["y1"] / H]
    return out


def editar_segmento(seg_id: int, texto: str) -> None:
    s = db.row("SELECT traduccion_id FROM segmentos WHERE id=?", (seg_id,))
    if not s:
        raise TranslateError("Segmento no encontrado.")
    with db.tx() as c:
        c.execute("UPDATE segmentos SET traducido=?, estado='ok', error=NULL WHERE id=?", (texto, seg_id))
    construir_pdf(s["traduccion_id"])


def reintentar_segmento(seg_id: int) -> dict:
    s = db.row("SELECT s.*, t.origen, t.destino FROM segmentos s JOIN traducciones t ON t.id=s.traduccion_id WHERE s.id=?",
               (seg_id,))
    if not s:
        raise TranslateError("Segmento no encontrado.")
    terminos = glossary.terminos_activos(load_settings()["traduccion"].get("glosarios_activos", []), s["origen"], s["destino"])
    t = traducir_textos([s["original"]], s["origen"], s["destino"], terminos)[0]
    with db.tx() as c:
        c.execute("UPDATE segmentos SET traducido=?, estado='ok', error=NULL WHERE id=?", (t.strip(), seg_id))
    construir_pdf(s["traduccion_id"])
    return db.row("SELECT * FROM segmentos WHERE id=?", (seg_id,))


def retraducir_con_termino(doc_id: int, destino: str, termino: str) -> int:
    """Como en PageBridge: tras añadir un término al glosario, solo se retraducen los párrafos que lo contienen."""
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if not t:
        raise TranslateError("Este documento no tiene traducción en ese idioma.")
    patron = re.compile(r"(?<!\w)" + re.escape(termino.strip()) + r"(?!\w)", re.I)
    segs = [s for s in db.rows("SELECT * FROM segmentos WHERE traduccion_id=? AND estado IN ('ok','error')", (t["id"],))
            if patron.search(s["original"])]
    if not segs:
        return 0
    terminos = glossary.terminos_activos(load_settings()["traduccion"].get("glosarios_activos", []), t["origen"], destino)
    _traducir_segmentos(segs, t["origen"], destino, terminos, llm.config_activa("traduccion"))
    construir_pdf(t["id"])
    return len(segs)


def borrar_traduccion(doc_id: int, destino: str) -> None:
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if not t:
        return
    with db.tx() as c:
        c.execute("DELETE FROM traducciones WHERE id=?", (t["id"],))
        c.execute("DELETE FROM texto_fts WHERE documento_id=? AND tipo='traduccion'", (doc_id,))
    Path(t["archivo"]).unlink(missing_ok=True)


def resumen_traduccion(doc_id: int, destino: str) -> dict:
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if not t:
        return {}
    cuenta = {r["estado"]: r["n"] for r in db.rows(
        "SELECT estado, COUNT(*) n FROM segmentos WHERE traduccion_id=? GROUP BY estado", (t["id"],))}
    pags = db.rows("SELECT pagina, SUM(estado='ok') ok, SUM(estado='error') err, SUM(estado='pendiente') pend"
                   " FROM segmentos WHERE traduccion_id=? GROUP BY pagina", (t["id"],))
    t["segmentos"] = cuenta
    t["paginas"] = pags
    return t


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
def exportar(doc_id: int, destino: str, modo: str = "traducido") -> Path:
    d = library.get(doc_id)
    t = db.row("SELECT * FROM traducciones WHERE documento_id=? AND destino=?", (doc_id, destino))
    if not t or not Path(t["archivo"]).exists():
        raise TranslateError("Primero traduce el documento.")
    nombre = library._nombre_seguro(d["titulo"])
    if modo == "traducido":
        out = EXPORT_DIR / f"{nombre} ({IDIOMAS.get(destino, destino)}).pdf"
        src = fitz.open(t["archivo"])
        src.save(out, garbage=3, deflate=True)
        src.close()
        return out
    original = fitz.open(d["archivo"])
    traducido = fitz.open(t["archivo"])
    salida = fitz.open()
    if modo == "bilingue_lado":
        for i in range(original.page_count):
            r = original[i].rect
            page = salida.new_page(width=r.width * 2, height=r.height)
            page.show_pdf_page(fitz.Rect(0, 0, r.width, r.height), original, i)
            page.show_pdf_page(fitz.Rect(r.width, 0, r.width * 2, r.height), traducido, i)
            page.draw_line(fitz.Point(r.width, 0), fitz.Point(r.width, r.height), color=(0, 0, 0), width=1.5)
        out = EXPORT_DIR / f"{nombre} (bilingüe lado a lado).pdf"
    else:  # bilingue_intercalado
        for i in range(original.page_count):
            salida.insert_pdf(original, from_page=i, to_page=i)
            salida.insert_pdf(traducido, from_page=i, to_page=i)
        out = EXPORT_DIR / f"{nombre} (bilingüe intercalado).pdf"
    salida.save(out, garbage=3, deflate=True)
    for x in (salida, original, traducido):
        x.close()
    return out

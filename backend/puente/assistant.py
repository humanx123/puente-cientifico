"""Asistente de documentos (PageBridge): preguntas sobre el documento, la página actual,
una selección o libres; respuestas con citas de página comprobables."""
from __future__ import annotations

import re

from . import db, glossary, library, llm
from .config import load_settings

MAX_CONTEXTO = 24000
VACIAS = set("""cual cuales cuál cuáles que qué como cómo donde dónde cuando cuándo por para con sin sobre entre los las del
una uno unos unas este esta estos estas ese esa eso son fue fueron hay tiene tienen documento artículo texto
the and for with what which how are was were this that from""".split())


def _paginas_relevantes(doc_id: int, pregunta: str, extra_terminos: list[str], n: int = 6) -> list[int]:
    palabras = [w for w in re.findall(r"\w{3,}", pregunta, flags=re.UNICODE) if w.lower() not in VACIAS] + extra_terminos
    if not palabras:
        return [1]
    # Prefijos (regla → reglas) y búsqueda en original y traducción (preguntas en español sobre textos en inglés)
    match = " OR ".join('"' + w.replace('"', "") + '"*' for w in palabras[:40])
    try:
        res = db.rows(
            "SELECT pagina, MIN(rank) r FROM texto_fts WHERE texto_fts MATCH ? AND documento_id=?"
            " GROUP BY pagina ORDER BY r LIMIT ?",
            (match, doc_id, n),
        )
    except Exception:
        res = []
    paginas = [r["pagina"] for r in res]
    if 1 not in paginas and len(paginas) < n:
        paginas.append(1)  # el resumen/título suele estar en la primera página
    return sorted(set(paginas)) or [1]


def _terminos_inversos(pregunta: str) -> list[str]:
    """Si la pregunta está en español, busca también los términos originales del glosario (PageBridge)."""
    s = load_settings()["traduccion"]
    out = []
    low = pregunta.lower()
    for g in glossary.listar():
        if g["id"] not in (s.get("glosarios_activos") or []) and not g["integrado"]:
            continue
        for a, b in g["terminos"]:
            if b.lower() in low:
                out.extend(re.findall(r"\w{3,}", a))
    return out[:20]


def preguntar(doc_id: int | None, pregunta: str, ambito: str = "documento", pagina: int | None = None,
              seleccion: str = "", historial: list[dict] | None = None) -> dict:
    pregunta = (pregunta or "").strip()
    if not pregunta:
        raise ValueError("Escribe una pregunta.")
    cfg = llm.config_activa("asistente")
    contexto, paginas = "", []
    titulo = ""
    if doc_id and ambito != "libre":
        d = library.get(doc_id)
        titulo = d["titulo"]
        if ambito == "pagina" and pagina:
            paginas = [pagina]
        elif ambito == "seleccion" and seleccion:
            paginas = [pagina] if pagina else []
        elif d["paginas"] <= 5:
            paginas = list(range(1, d["paginas"] + 1))  # documento corto: cabe entero
        else:
            paginas = _paginas_relevantes(doc_id, pregunta, _terminos_inversos(pregunta))
        partes = []
        if ambito == "seleccion" and seleccion:
            partes.append(f"[Selección del usuario, página {pagina or '?'}]\n{seleccion.strip()}")
        for p in paginas:
            try:
                txt = library.texto_pagina(doc_id, p)
            except Exception:
                continue
            partes.append(f"[Página {p}]\n{txt.strip()}")
        contexto = "\n\n".join(partes)[:MAX_CONTEXTO]
    sistema = (
        "Eres el asistente de investigación de Puente Científico. Responde SIEMPRE en español, con claridad y rigor. "
        "Cuando uses información del documento, cita la página con el formato [p. N]. "
        "Si el documento no contiene la respuesta, dilo explícitamente y no inventes datos."
    )
    mensajes = [{"role": "system", "content": sistema}]
    for h in (historial or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            mensajes.append({"role": h["role"], "content": str(h["content"])[:4000]})
    if contexto:
        usuario = f"Documento: «{titulo}»\n\nFragmentos:\n{contexto}\n\nPregunta: {pregunta}"
    else:
        usuario = pregunta
    mensajes.append({"role": "user", "content": usuario})
    respuesta = llm.chat(mensajes, cfg, temperatura=0.3)
    citas = sorted({int(n) for n in re.findall(r"\[p(?:ág)?\.?\s*(\d+)\]", respuesta, flags=re.I)})
    return {"respuesta": respuesta.strip(), "citas": citas, "paginas_consultadas": paginas,
            "modelo": llm.modelo_de(cfg)}


def resumir(doc_id: int) -> dict:
    return preguntar(doc_id, "Haz un resumen estructurado del documento: objetivo, métodos, resultados principales "
                             "y conclusiones, con citas de página.", "documento")

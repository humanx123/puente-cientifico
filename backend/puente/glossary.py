"""Glosarios de términos (adaptados de PageBridge, ahora inglés → español por defecto)."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter

import fitz

from . import db
from .config import BASE_DIR

BUILTIN = BASE_DIR / "datos" / "glosarios.json"

STOP = set("""
a an the of and or to in on for with by from at as is are was were be been being this that these those it its into than then
which who whom whose what when where why how not no nor but if so such can could may might must shall should will would do does did
we our you your they their he she his her them us i me my also both each other some any all most more less many much very
fig figure table et al using used use based between among within without over under after before during through per via
""".split())


def sembrar() -> None:
    if db.row("SELECT COUNT(*) n FROM glosarios WHERE integrado=1")["n"]:
        return
    try:
        data = json.loads(BUILTIN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    with db.tx() as c:
        for g in data:
            c.execute(
                "INSERT INTO glosarios(nombre, origen, destino, integrado, terminos) VALUES (?,?,?,1,?)",
                (g["nombre"], g["origen"], g["destino"], json.dumps(g["terminos"], ensure_ascii=False)),
            )


def listar(origen: str | None = None, destino: str | None = None) -> list[dict]:
    out = []
    for g in db.rows("SELECT * FROM glosarios ORDER BY integrado DESC, nombre COLLATE NOCASE"):
        if origen and g["origen"] != origen:
            continue
        if destino and g["destino"] != destino:
            continue
        g["terminos"] = json.loads(g["terminos"] or "[]")
        g["n"] = len(g["terminos"])
        out.append(g)
    return out


def obtener(gid: int) -> dict:
    g = db.row("SELECT * FROM glosarios WHERE id=?", (gid,))
    if not g:
        raise ValueError("Glosario no encontrado.")
    g["terminos"] = json.loads(g["terminos"] or "[]")
    return g


def _limpiar(terminos) -> list[list[str]]:
    vistos, out = set(), []
    for par in terminos or []:
        if not isinstance(par, (list, tuple)) or len(par) < 2:
            continue
        a, b = str(par[0]).strip(), str(par[1]).strip()
        if a and b and a.lower() not in vistos:
            vistos.add(a.lower())
            out.append([a, b])
    return out


def guardar(gid: int | None, nombre: str, origen: str, destino: str, terminos) -> dict:
    terminos = _limpiar(terminos)
    with db.tx() as c:
        if gid:
            c.execute(
                "UPDATE glosarios SET nombre=?, origen=?, destino=?, terminos=?, actualizado=datetime('now','localtime') WHERE id=?",
                (nombre, origen, destino, json.dumps(terminos, ensure_ascii=False), gid),
            )
        else:
            cur = c.execute(
                "INSERT INTO glosarios(nombre, origen, destino, terminos) VALUES (?,?,?,?)",
                (nombre, origen, destino, json.dumps(terminos, ensure_ascii=False)),
            )
            gid = cur.lastrowid
    return obtener(gid)


def duplicar(gid: int) -> dict:
    g = obtener(gid)
    return guardar(None, g["nombre"] + " (copia)", g["origen"], g["destino"], g["terminos"])


def borrar(gid: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM glosarios WHERE id=?", (gid,))


def agregar_termino(gid: int, origen: str, destino: str) -> dict:
    g = obtener(gid)
    terminos = [t for t in g["terminos"] if t[0].lower() != origen.strip().lower()]
    terminos.append([origen.strip(), destino.strip()])
    return guardar(gid, g["nombre"], g["origen"], g["destino"], terminos)


def importar_texto(contenido: str) -> list[list[str]]:
    """Acepta CSV (origen,destino) o TXT con tabulador, '=' o '->' como separador."""
    filas = []
    sample = contenido[:2000]
    if "," in sample and "\t" not in sample and "=" not in sample:
        for r in csv.reader(io.StringIO(contenido)):
            if len(r) >= 2:
                filas.append([r[0], r[1]])
    else:
        for line in contenido.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\t|\s*->\s*|\s*=\s*|\s*;\s*", line, maxsplit=1)
            if len(parts) == 2:
                filas.append(parts)
    return _limpiar(filas)


def exportar_csv(gid: int) -> str:
    g = obtener(gid)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["origen", "destino"])
    for a, b in g["terminos"]:
        w.writerow([a, b])
    return buf.getvalue()


def terminos_activos(ids: list[int], origen: str, destino: str) -> list[list[str]]:
    out: list[list[str]] = []
    for gid in ids or []:
        try:
            g = obtener(int(gid))
        except (ValueError, TypeError):
            continue
        if g["origen"] == origen and g["destino"] == destino:
            out.extend(g["terminos"])
    return _limpiar(out)


def coincidencias(texto: str, terminos: list[list[str]], limite: int = 40) -> list[list[str]]:
    low = texto.lower()
    hits = []
    for a, b in terminos:
        al = a.lower()
        if re.search(r"(?<!\w)" + re.escape(al) + r"(?!\w)", low):
            hits.append([a, b])
            if len(hits) >= limite:
                break
    return hits


def sugerir_terminos(ruta_pdf: str, limite: int = 50) -> list[dict]:
    """Extrae términos candidatos del documento (n-gramas frecuentes, sin palabras vacías)."""
    pdf = fitz.open(ruta_pdf)
    try:
        texto = " ".join(p.get_text("text") for p in pdf)
    finally:
        pdf.close()
    palabras = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", texto)
    low = [w.lower() for w in palabras]
    cont: Counter = Counter()
    for n in (1, 2, 3):
        for i in range(len(low) - n + 1):
            gram = low[i:i + n]
            if gram[0] in STOP or gram[-1] in STOP or any(len(g) < 3 for g in gram):
                continue
            if n == 1 and (gram[0] in STOP or len(gram[0]) < 6):
                continue
            cont[" ".join(gram)] += 1
    candidatos = []
    for term, n in cont.most_common(limite * 4):
        if n < 3:
            break
        peso = n * (1.0 + 0.6 * term.count(" "))
        candidatos.append({"termino": term, "frecuencia": n, "peso": round(peso, 1)})
    candidatos.sort(key=lambda x: -x["peso"])
    # Quitar unigramas contenidos en n-gramas más fuertes
    finales = []
    for c in candidatos:
        if any(c["termino"] != f["termino"] and c["termino"] in f["termino"] and f["frecuencia"] >= c["frecuencia"] * 0.7 for f in finales):
            continue
        finales.append(c)
        if len(finales) >= limite:
            break
    return finales

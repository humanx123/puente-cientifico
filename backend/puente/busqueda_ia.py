"""Búsqueda de literatura asistida por IA (FreeLLMAPI / proveedor configurado).

1. El modelo convierte la pregunta (en cualquier idioma) en 2–4 consultas bibliográficas en inglés,
   con título probable, autores y rango de años si los menciona.
2. Se lanzan en OpenAlex (o Crossref si se agota el cupo) y se combinan sin duplicados.
3. El modelo puntúa la relevancia de cada resultado y explica en una frase por qué encaja.
"""
from __future__ import annotations

import json
import re

from . import literature, llm


def _json(texto: str):
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip())
    for cand in (texto, texto[texto.find("{"): texto.rfind("}") + 1] if "{" in texto else ""):
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def planificar(pregunta: str) -> dict:
    sistema = (
        "Eres un bibliotecario científico experto. Convierte la necesidad del usuario en búsquedas para OpenAlex. "
        "Responde SOLO con JSON: {\"consultas\": [2-4 cadenas cortas en inglés con los términos técnicos clave, "
        "sin operadores], \"titulo\": \"título exacto si el usuario lo cita, si no vacío\", \"autor\": \"apellido o "
        "nombre de un autor si lo menciona, si no vacío\", \"desde\": año o null, \"hasta\": año o null, "
        "\"explicacion\": \"una frase en español sobre la estrategia\"}"
    )
    r = llm.chat([{"role": "system", "content": sistema}, {"role": "user", "content": pregunta}],
                 llm.config_activa("asistente"), temperatura=0.2, json_mode=True, timeout=120)
    plan = _json(r) or {}
    consultas = [c.strip() for c in plan.get("consultas") or [] if isinstance(c, str) and c.strip()][:4]
    if not consultas and not plan.get("titulo"):
        consultas = [pregunta[:200]]
    plan["consultas"] = consultas
    return plan


def puntuar(pregunta: str, obras: list[dict]) -> dict[str, dict]:
    lista = [{"i": i, "titulo": o["titulo"][:220], "anio": o.get("anio"), "revista": (o.get("revista") or "")[:80]}
             for i, o in enumerate(obras[:30])]
    sistema = (
        "Evalúa qué tan útil es cada artículo para la necesidad del usuario. Responde SOLO con JSON: "
        "{\"puntuaciones\": [{\"i\": índice, \"p\": 0-10, \"motivo\": \"frase breve en español\"}]}. "
        "Incluye todos los índices."
    )
    usuario = f"Necesidad: {pregunta}\n\nArtículos:\n{json.dumps(lista, ensure_ascii=False)}"
    try:
        r = llm.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                     llm.config_activa("asistente"), temperatura=0.1, json_mode=True, timeout=150)
        datos = _json(r) or {}
    except llm.LLMError:
        return {}
    out = {}
    for p in datos.get("puntuaciones") or []:
        try:
            i = int(p.get("i"))
            out[obras[i]["id"]] = {"p": float(p.get("p", 0)), "motivo": str(p.get("motivo", ""))[:200]}
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return out


def buscar(pregunta: str, solo_abierto: bool = False) -> dict:
    pregunta = (pregunta or "").strip()
    if len(pregunta) < 4:
        raise literature.LitError("Describe con un poco más de detalle qué buscas.")
    plan = planificar(pregunta)
    obras, vistos, fuentes, avisos = [], set(), set(), []
    trabajos = [("todo", c, "", "") for c in plan["consultas"]]
    if plan.get("titulo"):
        trabajos.insert(0, ("titulo", "", plan["titulo"], plan.get("autor") or ""))
    elif plan.get("autor"):
        trabajos.append(("todo", plan["consultas"][0] if plan["consultas"] else "", "", plan["autor"]))
    for modo, q, titulo, autor in trabajos[:5]:
        try:
            r = literature.buscar(q=q, titulo=titulo, autor=autor, modo="todo" if not titulo else "titulo",
                                  solo_abierto=solo_abierto, desde=plan.get("desde"), hasta=plan.get("hasta"))
        except literature.LitError as e:
            avisos.append(str(e))
            continue
        fuentes.add(r.get("fuente", "openalex"))
        if r.get("aviso"):
            avisos.append(r["aviso"])
        for o in r["obras"][:15]:
            k = o.get("doi") or o["id"]
            if k not in vistos:
                vistos.add(k)
                obras.append(o)
    puntos = puntuar(pregunta, obras) if obras else {}
    for o in obras:
        pp = puntos.get(o["id"])
        o["relevancia"] = pp["p"] if pp else None
        o["motivo_ia"] = pp["motivo"] if pp else ""
    obras.sort(key=lambda o: -(o["relevancia"] if o["relevancia"] is not None else -1))
    return {"obras": obras[:30], "total": len(obras), "pagina": 1, "hay_mas": False, "plan": plan,
            "fuente": "+".join(sorted(fuentes)) or "openalex", "creditos": literature.creditos(),
            "aviso": " ".join(dict.fromkeys(avisos))[:400], "modelo": llm.modelo_de(llm.config_activa("asistente"))}

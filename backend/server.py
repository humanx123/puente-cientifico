"""API local de Puente Científico (FastAPI). La sirve run.py dentro de una ventana nativa."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from puente import APP_NAME, __version__, assistant, db, freellmapi, glossary, library, literature, llm, news, translate
from puente.config import BASE_DIR, DATA, EXPORT_DIR, SECRETOS, load_settings, public_settings, save_settings

app = FastAPI(title=APP_NAME, version=__version__)
STATIC = BASE_DIR / "static"
WINDOW = {"ventana": None}  # la rellena run.py para los diálogos nativos

db.init()
glossary.sembrar()
news.sembrar()


def _configurar_freellmapi() -> None:
    """Primer arranque: si FreeLLMAPI está instalado en este equipo, importa su clave unificada."""
    t = load_settings()["traduccion"]
    if t["proveedor"] == "freellmapi" and not t.get("freellmapi_clave"):
        try:
            save_settings({"traduccion": {"freellmapi_clave": freellmapi.leer_clave(t.get("freellmapi_ruta"))}})
        except Exception:
            pass  # sin instalación local: el usuario pega la clave o cambia la URL en Ajustes


_configurar_freellmapi()

ERRORES_USUARIO = (library.LibraryError, translate.TranslateError, literature.LitError, llm.LLMError, ValueError)


def enriquecer(doc: dict) -> None:
    """Si el PDF trae DOI, completa título, autores y año desde OpenAlex en segundo plano."""
    if not doc or doc.get("duplicado") or not doc.get("doi"):
        return

    def tarea():
        try:
            obra = literature.metadatos_doi(doc["doi"])
            if obra:
                library.actualizar(doc["id"], {"titulo": obra["titulo"], "autores": ", ".join(obra["autores"]),
                                               "anio": obra["anio"]})
        except Exception:
            pass

    threading.Thread(target=tarea, daemon=True).start()


@app.exception_handler(Exception)
async def _errores(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if isinstance(exc, ERRORES_USUARIO):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"detail": f"Error interno: {exc}"}, status_code=500)


# ---------------------------------------------------------------------------
# Sistema
# ---------------------------------------------------------------------------
@app.get("/api/estado")
def estado():
    return {"app": APP_NAME, "version": __version__, "datos": str(DATA), "exportaciones": str(EXPORT_DIR),
            "carpeta": str(BASE_DIR), "estadisticas": library.estadisticas(), "ventana_nativa": WINDOW["ventana"] is not None}


@app.get("/api/instancia")
def instancia():
    return {"carpeta": str(BASE_DIR), "app": APP_NAME}


@app.get("/api/ajustes")
def ajustes():
    return public_settings()


@app.put("/api/ajustes")
def guardar_ajustes(patch: dict = Body(...)):
    # Las claves vacías desde la interfaz significan "no cambiar"
    for sec, key in SECRETOS:
        if sec in patch and key in patch[sec] and not patch[sec][key]:
            patch[sec].pop(key)
        if sec in patch:
            patch[sec].pop(key + "_configurada", None)
    if patch.get("borrar_clave"):
        sec, key = patch.pop("borrar_clave").split(".")
        patch.setdefault(sec, {})[key] = ""
    save_settings(patch)
    return public_settings()


@app.post("/api/abrir-url")
def abrir_url(datos: dict = Body(...)):
    url = str(datos.get("url", ""))
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Solo se pueden abrir direcciones web.")
    webbrowser.open(url)
    return {"ok": True}


@app.post("/api/abrir-ruta")
def abrir_ruta(datos: dict = Body(...)):
    ruta = Path(str(datos.get("ruta", "")))
    if not ruta.exists():
        raise HTTPException(404, "La ruta no existe.")
    if datos.get("mostrar") and ruta.is_file():
        subprocess.Popen(["explorer", "/select,", str(ruta)])
    else:
        os.startfile(str(ruta))  # noqa: S606 (abre con la app predeterminada de Windows)
    return {"ok": True}


@app.post("/api/diagnostico")
def diagnostico():
    from puente import diagnostico_red
    return diagnostico_red.ejecutar()


@app.post("/api/diagnostico/reparar")
def diagnostico_reparar():
    from puente import diagnostico_red
    return diagnostico_red.reparar()


@app.post("/api/ventana/mostrar")
def ventana_mostrar():
    """La segunda copia de la app pide a esta que traiga su ventana al frente."""
    v = WINDOW["ventana"]
    if v is None:
        return {"ok": False}
    try:
        v.restore()
        v.show()
        v.on_top = True
        v.on_top = False
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/dialogo")
def dialogo(datos: dict = Body(...)):
    """Diálogos nativos de Windows (abrir PDF, carpeta o guardar)."""
    ventana = WINDOW["ventana"]
    if ventana is None:
        raise HTTPException(409, "Diálogo nativo no disponible en el navegador.")
    import webview
    tipo = datos.get("tipo", "abrir")
    if tipo == "carpeta":
        res = ventana.create_file_dialog(webview.FOLDER_DIALOG)
    elif tipo == "guardar":
        res = ventana.create_file_dialog(webview.SAVE_DIALOG, save_filename=datos.get("nombre", "archivo.pdf"))
    else:
        filtros = tuple(datos.get("filtros") or ("PDF y libros (*.pdf;*.epub;*.mobi;*.fb2;*.cbz;*.xps;*.oxps)",
                                                 "Documentos PDF (*.pdf)", "Todos los archivos (*.*)"))
        res = ventana.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=bool(datos.get("multiple", True)),
                                         file_types=filtros)
    if not res:
        return {"rutas": []}
    return {"rutas": [res] if isinstance(res, str) else list(res)}


@app.post("/api/copiar-a")
def copiar_a(datos: dict = Body(...)):
    origen, destino = Path(datos["origen"]), Path(datos["destino"])
    if not origen.exists():
        raise HTTPException(404, "El archivo de origen no existe.")
    shutil.copyfile(origen, destino)
    return {"ruta": str(destino)}


@app.get("/api/archivo")
def archivo(ruta: str):
    p = Path(ruta).resolve()
    permitido = [DATA.resolve(), EXPORT_DIR.resolve()]
    if not any(str(p).startswith(str(b)) for b in permitido) or not p.exists():
        raise HTTPException(404, "Archivo no disponible.")
    return FileResponse(p, filename=p.name)


# ---------------------------------------------------------------------------
# Biblioteca
# ---------------------------------------------------------------------------
@app.get("/api/documentos")
def documentos(vista: str = "todos", carpeta: int | None = None, q: str = "", orden: str = "agregado"):
    return library.listar(vista, carpeta, q, orden)


@app.post("/api/documentos/subir")
async def subir(archivos: list[UploadFile] = File(...), carpeta: int | None = None):
    resultados = []
    for a in archivos:
        sufijo = Path(a.filename or "x.pdf").suffix.lower()
        sufijo = sufijo if sufijo in library.EBOOKS | {".pdf"} else ".pdf"
        fd, nombre_tmp = tempfile.mkstemp(suffix=sufijo)
        os.close(fd)
        tmp = Path(nombre_tmp)
        try:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(a.file, f)
            try:
                d = library.import_pdf(tmp, carpeta_id=carpeta)
                if not d.get("titulo") or d["titulo"] == tmp.stem:
                    d = library.actualizar(d["id"], {"titulo": Path(a.filename).stem})
                enriquecer(d)
                resultados.append({"ok": True, "nombre": a.filename, "documento": d})
            except library.LibraryError as e:
                resultados.append({"ok": False, "nombre": a.filename, "error": str(e)})
        finally:
            tmp.unlink(missing_ok=True)
    return resultados


@app.post("/api/documentos/importar-rutas")
def importar_rutas(datos: dict = Body(...)):
    rutas = []
    for r in datos.get("rutas", []):
        p = Path(r)
        if p.is_dir():
            rutas += sorted(x for x in p.rglob("*") if x.suffix.lower() in library.EBOOKS | {".pdf"})
        else:
            rutas.append(p)
    resultados = []
    for p in rutas[:2000]:
        try:
            d = library.import_pdf(p, carpeta_id=datos.get("carpeta"))
            enriquecer(d)
            resultados.append({"ok": True, "nombre": p.name, "documento": d})
        except library.LibraryError as e:
            resultados.append({"ok": False, "nombre": p.name, "error": str(e)})
    return resultados


@app.post("/api/documentos/cargar-demo")
def cargar_demo():
    demo = BASE_DIR / "datos" / "demo"
    res = []
    for p in sorted(demo.glob("*.pdf")):
        try:
            d = library.import_pdf(p, origen="ejemplo")
            enriquecer(d)
            res.append(d)
        except library.LibraryError:
            pass
    return res


@app.get("/api/documentos/{doc_id}")
def documento(doc_id: int):
    return library.get(doc_id)


@app.patch("/api/documentos/{doc_id}")
def actualizar(doc_id: int, campos: dict = Body(...)):
    return library.actualizar(doc_id, campos)


@app.post("/api/documentos/{doc_id}/abierto")
def abierto(doc_id: int):
    library.marcar_abierto(doc_id)
    return {"ok": True}


@app.post("/api/documentos/{doc_id}/papelera")
def papelera(doc_id: int):
    library.a_papelera(doc_id)
    return {"ok": True}


@app.post("/api/documentos/{doc_id}/restaurar")
def restaurar(doc_id: int):
    library.restaurar(doc_id)
    return {"ok": True}


@app.delete("/api/documentos/{doc_id}")
def borrar(doc_id: int):
    library.borrar_definitivo(doc_id)
    return {"ok": True}


@app.post("/api/papelera/vaciar")
def vaciar():
    return {"borrados": library.vaciar_papelera()}


@app.get("/api/documentos/{doc_id}/paginas")
def paginas(doc_id: int):
    return library.info_paginas(doc_id)


@app.get("/api/documentos/{doc_id}/indice")
def indice(doc_id: int):
    return library.indice(doc_id)


@app.get("/api/documentos/{doc_id}/pagina/{n}.png")
def pagina_png(doc_id: int, n: int, zoom: float = 1.5, variante: str = "original"):
    p = library.render(doc_id, n, zoom, variante)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/documentos/{doc_id}/texto/{n}")
def texto(doc_id: int, n: int, variante: str = "original"):
    return library.capa_texto(doc_id, n, variante)


@app.get("/api/documentos/{doc_id}/buscar")
def buscar_doc(doc_id: int, q: str, variante: str = "original"):
    return library.buscar_en_documento(doc_id, q, variante)


@app.get("/api/documentos/{doc_id}/pdf")
def pdf_original(doc_id: int, variante: str = "original"):
    return FileResponse(library.ruta_variante(doc_id, variante), media_type="application/pdf")


@app.get("/api/buscar")
def buscar_global(q: str):
    return library.busqueda_global(q)


@app.get("/api/carpetas")
def carpetas():
    return library.carpetas()


def _padre(valor) -> int | None:
    """Convierte el id de carpeta padre recibido (None, '' o número) a int | None."""
    if valor in (None, "", 0, "0"):
        return None
    return int(valor)


@app.post("/api/carpetas")
def crear_carpeta(datos: dict = Body(...)):
    return library.crear_carpeta(datos.get("nombre", ""), _padre(datos.get("padre_id")))


@app.patch("/api/carpetas/{cid}")
def editar_carpeta(cid: int, datos: dict = Body(...)):
    """Renombra y/o mueve la carpeta. Solo se aplica lo que venga en el cuerpo."""
    if "nombre" in datos:
        library.renombrar_carpeta(cid, datos.get("nombre", ""))
    if "padre_id" in datos:
        library.mover_carpeta(cid, _padre(datos.get("padre_id")))
    return {"ok": True}


@app.delete("/api/carpetas/{cid}")
def borrar_carpeta(cid: int):
    library.borrar_carpeta(cid)
    return {"ok": True}


# Notas -----------------------------------------------------------------------
@app.get("/api/documentos/{doc_id}/notas")
def notas(doc_id: int):
    return library.notas(doc_id)


@app.post("/api/documentos/{doc_id}/notas")
def crear_nota(doc_id: int, datos: dict = Body(...)):
    return library.crear_nota(doc_id, int(datos.get("pagina", 1)), datos.get("tipo", "nota"), datos.get("texto", ""),
                              datos.get("cita", ""), datos.get("color", "#ffe600"))


@app.patch("/api/notas/{nid}")
def editar_nota(nid: int, datos: dict = Body(...)):
    library.editar_nota(nid, datos.get("texto", ""))
    return {"ok": True}


@app.delete("/api/notas/{nid}")
def borrar_nota(nid: int):
    library.borrar_nota(nid)
    return {"ok": True}


@app.get("/api/documentos/{doc_id}/resaltados/{pagina}")
def resaltados(doc_id: int, pagina: int):
    out = []
    for n in library.notas(doc_id):
        if n["pagina"] == pagina and n["tipo"] in ("resaltado", "subrayado") and n["cita"]:
            out.append({"id": n["id"], "tipo": n["tipo"], "color": n["color"],
                        "rects": library.rects_de_cita(doc_id, pagina, n["cita"])})
    return out


@app.post("/api/documentos/{doc_id}/exportar")
def exportar(doc_id: int, datos: dict = Body(...)):
    tipo = datos.get("tipo", "anotado")
    if tipo == "anotado":
        ruta = library.exportar_anotado(doc_id)
    elif tipo == "markdown":
        ruta = library.exportar_markdown(doc_id)
    else:
        ruta = translate.exportar(doc_id, datos.get("destino", "es"), tipo)
    return {"ruta": str(ruta), "nombre": ruta.name}


# ---------------------------------------------------------------------------
# Traducción e IA
# ---------------------------------------------------------------------------
@app.get("/api/idiomas")
def idiomas():
    return translate.IDIOMAS


@app.get("/api/modelos")
def modelos(proveedor: str | None = None):
    cfg = llm.config_activa("traduccion")
    if proveedor:
        cfg["proveedor"] = proveedor
    return llm.listar_modelos(cfg)


@app.post("/api/probar-modelo")
def probar_modelo(datos: dict = Body(default={})):
    cfg = llm.config_activa(datos.get("para", "traduccion"))
    t = translate.traducir_textos(["The virus replicates in the host cell."], "en", "es", [], cfg)
    via = llm.ULTIMA_RUTA["via"] if cfg["proveedor"] != "ollama" else ""
    return {"ok": True, "modelo": llm.modelo_de(cfg) + (f" → {via}" if via else ""), "muestra": t[0]}


@app.get("/api/freellmapi/estado")
def fl_estado():
    return freellmapi.estado(llm.config_activa("traduccion"))


@app.post("/api/freellmapi/importar-clave")
def fl_importar(datos: dict = Body(default={})):
    ruta = datos.get("ruta") or load_settings()["traduccion"].get("freellmapi_ruta")
    clave = freellmapi.leer_clave(ruta)
    save_settings({"traduccion": {"freellmapi_clave": clave, "proveedor": "freellmapi"}})
    return freellmapi.estado(llm.config_activa("traduccion"))


@app.post("/api/freellmapi/arrancar")
def fl_arrancar():
    cfg = llm.config_activa("traduccion")
    if not freellmapi.responde(cfg["freellmapi_url"])[0] and not freellmapi.arrancar(cfg.get("freellmapi_ruta"), cfg["freellmapi_url"]):
        raise HTTPException(400, "No pude iniciar FreeLLMAPI. Comprueba la carpeta de instalación y que Node.js esté instalado.")
    return freellmapi.estado(cfg)


@app.post("/api/traducir")
def traducir(datos: dict = Body(...)):
    s = load_settings()["traduccion"]
    return translate.iniciar(int(datos["doc_id"]), datos.get("origen") or s["idioma_origen"],
                             datos.get("destino") or s["idioma_destino"], datos.get("rango", ""),
                             datos.get("glosarios"), bool(datos.get("reintentar_errores", True)))


@app.get("/api/trabajos")
def trabajos():
    return translate.trabajos()


@app.post("/api/trabajos/{jid}/cancelar")
def cancelar(jid: str):
    translate.cancelar(jid)
    return {"ok": True}


@app.get("/api/documentos/{doc_id}/traduccion/{destino}")
def resumen_trad(doc_id: int, destino: str):
    return translate.resumen_traduccion(doc_id, destino)


@app.delete("/api/documentos/{doc_id}/traduccion/{destino}")
def borrar_trad(doc_id: int, destino: str):
    translate.borrar_traduccion(doc_id, destino)
    return {"ok": True}


@app.get("/api/documentos/{doc_id}/segmentos/{destino}/{pagina}")
def segmentos(doc_id: int, destino: str, pagina: int):
    return translate.segmentos(doc_id, destino, pagina)


@app.put("/api/segmentos/{sid}")
def editar_segmento(sid: int, datos: dict = Body(...)):
    translate.editar_segmento(sid, datos.get("texto", ""))
    return {"ok": True}


@app.post("/api/segmentos/{sid}/reintentar")
def reintentar(sid: int):
    return translate.reintentar_segmento(sid)


@app.post("/api/documentos/{doc_id}/retraducir-termino")
def retraducir(doc_id: int, datos: dict = Body(...)):
    return {"segmentos": translate.retraducir_con_termino(doc_id, datos["destino"], datos["termino"])}


# Glosarios -------------------------------------------------------------------
@app.get("/api/glosarios")
def glosarios(origen: str | None = None, destino: str | None = None):
    return glossary.listar(origen, destino)


@app.post("/api/glosarios")
def crear_glosario(datos: dict = Body(...)):
    return glossary.guardar(None, datos.get("nombre", "Nuevo glosario"), datos.get("origen", "en"),
                            datos.get("destino", "es"), datos.get("terminos", []))


@app.put("/api/glosarios/{gid}")
def guardar_glosario(gid: int, datos: dict = Body(...)):
    return glossary.guardar(gid, datos["nombre"], datos["origen"], datos["destino"], datos.get("terminos", []))


@app.delete("/api/glosarios/{gid}")
def borrar_glosario(gid: int):
    glossary.borrar(gid)
    return {"ok": True}


@app.post("/api/glosarios/{gid}/duplicar")
def duplicar_glosario(gid: int):
    return glossary.duplicar(gid)


@app.post("/api/glosarios/{gid}/termino")
def agregar_termino(gid: int, datos: dict = Body(...)):
    return glossary.agregar_termino(gid, datos["origen"], datos["destino"])


@app.post("/api/glosarios/analizar")
def analizar_texto(datos: dict = Body(...)):
    return glossary.importar_texto(datos.get("contenido", ""))


@app.get("/api/glosarios/{gid}/csv")
def glosario_csv(gid: int):
    g = glossary.obtener(gid)
    return PlainTextResponse(glossary.exportar_csv(gid), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="glosario-{gid}.csv"'})


@app.get("/api/documentos/{doc_id}/sugerir-terminos")
def sugerir(doc_id: int):
    return glossary.sugerir_terminos(library.get(doc_id)["archivo"])


# Asistente -------------------------------------------------------------------
@app.post("/api/asistente")
def asistente(datos: dict = Body(...)):
    return assistant.preguntar(datos.get("doc_id"), datos.get("pregunta", ""), datos.get("ambito", "documento"),
                               datos.get("pagina"), datos.get("seleccion", ""), datos.get("historial"))


@app.post("/api/asistente/resumen/{doc_id}")
def resumen(doc_id: int):
    return assistant.resumir(doc_id)


# ---------------------------------------------------------------------------
# Literatura
# ---------------------------------------------------------------------------
@app.get("/api/literatura/buscar")
def lit_buscar(q: str = "", pagina: int = 1, abierto: bool = False, desde: int | None = None, hasta: int | None = None,
               orden: str = "relevancia", modo: str = "todo", titulo: str = "", autor: str = "", autor_id: str = "",
               autor_nombre: str = ""):
    return literature.buscar(q, pagina, abierto, desde, hasta, orden, modo, titulo, autor, autor_id, autor_nombre)


@app.post("/api/literatura/buscar-ia")
def lit_buscar_ia(datos: dict = Body(...)):
    from puente import busqueda_ia
    return busqueda_ia.buscar(datos.get("pregunta", ""), bool(datos.get("abierto")))


@app.post("/api/literatura/trabajos/{jid}/verificar")
def lit_verificar(jid: str):
    return literature.abrir_verificacion(jid)


@app.post("/api/literatura/probar-openalex")
def lit_probar_openalex():
    return literature.probar_openalex()


@app.get("/api/literatura/creditos")
def lit_creditos():
    return literature.creditos()


@app.get("/api/literatura/autor/{aid}")
def lit_autor(aid: str):
    return literature.autor(aid)


@app.get("/api/literatura/autores")
def lit_autores(q: str):
    return literature.buscar_autores(q)


@app.get("/api/libgen/buscar")
def libgen_buscar(q: str, modo: str = "todo", temas: str = "libros", pagina: int = 1, extension: str = "",
                  idioma: str = "", anio: str = ""):
    from puente import libgen
    try:
        return libgen.buscar(q, modo, [t for t in temas.split(",") if t], pagina, extension, idioma, anio)
    except libgen.LibgenError as e:
        raise HTTPException(400, str(e))


@app.post("/api/libgen/descargar")
def libgen_descargar(datos: dict = Body(...)):
    if datos.get("libros"):
        return literature.encolar_libros(datos["libros"], datos.get("fuente", "libgen"))
    return literature.encolar_libro(datos.get("libro"), datos.get("fuente", "libgen"))


def _bajar_imagen(url: str) -> bytes:
    literature.url_publica(url)
    try:
        r = literature.sesion().get(url, timeout=20, stream=True)
    except Exception:
        return b""
    if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
        return b""
    datos = r.raw.read(3 * 1024 * 1024 + 1, decode_content=True)
    return datos if 200 < len(datos) <= 3 * 1024 * 1024 else b""


@app.get("/api/portada")
def portada(url: str = "", titulo: str = "", autor: str = ""):
    """Portadas de LibGen/Anna's pedidas desde aquí (por el túnel si está activo) y en caché.
    LibGen a veces sirve portadas vacías: entonces se busca en Open Library por título y autor."""
    import hashlib
    from puente.config import CACHE_DIR
    carpeta = CACHE_DIR / "portadas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / (hashlib.sha1(f"{url}|{titulo}|{autor}".encode()).hexdigest() + ".img")
    vacia = ruta.with_suffix(".sin")
    if not ruta.exists():
        if vacia.exists():
            raise HTTPException(404, "Portada no disponible.")
        datos = _bajar_imagen(url) if url else b""
        if not datos and titulo:
            try:
                r = literature.sesion().get("https://openlibrary.org/search.json", timeout=15, params={
                    "title": titulo[:120], "author": (autor or "").split(";")[0].split(",")[0][:80], "limit": 1, "fields": "cover_i"})
                cid = (r.json().get("docs") or [{}])[0].get("cover_i")
                if cid:
                    datos = _bajar_imagen(f"https://covers.openlibrary.org/b/id/{int(cid)}-M.jpg")
            except Exception:
                datos = b""
        if not datos:
            vacia.touch()  # no volver a intentar en cada render
            raise HTTPException(404, "Portada no disponible.")
        ruta.write_bytes(datos)
    return FileResponse(ruta, media_type="image/jpeg", headers={"Cache-Control": "max-age=604800"})


@app.get("/api/annas/buscar")
def annas_buscar(q: str, modo: str = "todo", tipos: str = "", extension: str = "", idioma: str = "",
                 orden: str = "relevancia", pagina: int = 1):
    from puente import annas
    try:
        return annas.buscar(q, modo, [t for t in tipos.split(",") if t], extension, idioma, orden, pagina)
    except annas.AnnasError as e:
        raise HTTPException(400, str(e))


@app.get("/api/tunel")
def tunel_estado():
    from puente import tunel
    return tunel.estado()


@app.post("/api/tunel/{accion}")
def tunel_accion(accion: str):
    from puente import tunel
    if accion == "iniciar":
        try:
            return tunel.iniciar()
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    if accion == "detener":
        return tunel.detener()
    raise HTTPException(404, "Acción desconocida.")


@app.post("/api/literatura/descargar")
def lit_descargar(datos: dict = Body(...)):
    if datos.get("obras"):
        return literature.encolar_obras(datos["obras"], datos.get("fuente"))
    return literature.encolar(datos.get("consultas", ""), datos.get("fuente"), datos.get("obra"))


@app.get("/api/literatura/trabajos")
def lit_trabajos():
    return literature.listar_trabajos()


@app.post("/api/literatura/trabajos/{jid}/captcha")
def lit_captcha(jid: str, datos: dict = Body(...)):
    return literature.responder_captcha(jid, datos.get("respuesta"))


@app.post("/api/literatura/limpiar")
def lit_limpiar():
    literature.limpiar_trabajos()
    return {"ok": True}


@app.get("/api/literatura/historial")
def lit_historial():
    return literature.historial()


# ---------------------------------------------------------------------------
# Noticias
# ---------------------------------------------------------------------------
@app.get("/api/noticias")
def noticias(q: str = "", nivel: str = "", area: str = "", categoria: str = "", fuente: str = "",
             guardadas: bool = False, no_leidas: bool = False):
    return news.listar(q, nivel, area, categoria, fuente, guardadas, no_leidas)


@app.get("/api/noticias/facetas")
def facetas():
    return news.facetas()


@app.get("/api/noticias/estado")
def noticias_estado():
    return news.estado()


@app.post("/api/noticias/actualizar")
def noticias_actualizar():
    return news.recolectar_todo()


@app.patch("/api/noticias/{uid}")
def noticia_marcar(uid: str, datos: dict = Body(...)):
    news.marcar(uid, datos.get("leida"), datos.get("guardada"))
    return {"ok": True}


@app.get("/api/noticias/fuentes")
def fuentes():
    return news.fuentes()


@app.post("/api/noticias/fuentes")
def guardar_fuente(datos: dict = Body(...)):
    return news.guardar_fuente(datos)


@app.post("/api/noticias/fuentes/probar")
def probar_fuente(datos: dict = Body(...)):
    return news.probar_fuente(datos)


@app.post("/api/noticias/fuentes/{fid}/activa")
def activar_fuente(fid: str, datos: dict = Body(...)):
    news.activar_fuente(fid, bool(datos.get("activa", True)))
    return {"ok": True}


@app.delete("/api/noticias/fuentes/{fid}")
def borrar_fuente(fid: str):
    news.borrar_fuente(fid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Interfaz React compilada
# ---------------------------------------------------------------------------
if (STATIC / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{ruta:path}")
def spa(ruta: str):
    if ruta.startswith("api/"):
        raise HTTPException(404, "Ruta de API desconocida.")
    archivo_ = STATIC / ruta
    if ruta and archivo_.is_file() and STATIC in archivo_.resolve().parents:
        return FileResponse(archivo_)
    index = STATIC / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return Response("<h1>Puente Científico</h1><p>Falta compilar la interfaz (frontend).</p>", media_type="text/html")

import { useEffect, useState } from 'react'
import { Languages, Download, FolderOpen, ExternalLink, Save, RotateCcw, X, BookA, Check } from 'lucide-react'
import { api, abrirRuta, dialogoNativo, IDIOMAS_UI } from '../api.js'
import { Campo, Casilla, Modal, useAviso } from '../ui.jsx'

export function ModalTraducir({ doc, ajustes, trabajo, onCerrar, onIniciado }) {
  const avisar = useAviso()
  const t = ajustes?.traduccion || {}
  const [origen, setOrigen] = useState(t.idioma_origen || 'en')
  const [destino, setDestino] = useState(t.idioma_destino || 'es')
  const [rango, setRango] = useState('')
  const [glosarios, setGlosarios] = useState([])
  const [activos, setActivos] = useState(t.glosarios_activos || [])
  const [reintentar, setReintentar] = useState(true)
  const [resumen, setResumen] = useState(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => { api.get(`/api/glosarios?origen=${origen}&destino=${destino}`).then(setGlosarios).catch(() => {}) }, [origen, destino])
  useEffect(() => { api.get(`/api/documentos/${doc.id}/traduccion/${destino}`).then(setResumen).catch(() => setResumen(null)) }, [doc.id, destino])

  const iniciar = async () => {
    setEnviando(true)
    try {
      await api.put('/api/ajustes', { traduccion: { idioma_origen: origen, idioma_destino: destino, glosarios_activos: activos } })
      await api.post('/api/traducir', { doc_id: doc.id, origen, destino, rango, glosarios: activos, reintentar_errores: reintentar })
      avisar('Traducción en marcha. Puedes seguir leyendo.', 'ok')
      onIniciado(destino)
    } catch (e) { avisar(e.message, 'error') } finally { setEnviando(false) }
  }

  const proveedor = t.proveedor === 'ollama' ? `Ollama · ${t.ollama_modelo || 'SIN MODELO'}`
    : t.proveedor === 'freellmapi' ? `FreeLLMAPI · ${t.freellmapi_modelo || 'auto'}` : `API · ${t.openai_modelo}`
  const segs = resumen?.segmentos || {}
  return (
    <Modal titulo="Traducir con maquetación" onCerrar={onCerrar} pie={<>
      <button className="btn" onClick={onCerrar}>Cancelar</button>
      <button className="btn primario" onClick={iniciar} disabled={enviando || !!trabajo}><Languages size={16} />{trabajo ? 'Ya hay una traducción en curso' : 'Iniciar traducción'}</button>
    </>}>
      <div className="aviso-legal" style={{ background: 'var(--papel-2)', color: 'var(--tinta)' }}>
        Se conserva el número de páginas, columnas, figuras, fondos y tablas. Cada párrafo se traduce en su sitio y se ajusta el tamaño de letra para que quepa.
        <div className="mono" style={{ marginTop: 6, fontSize: 11 }}>MOTOR: {proveedor.toUpperCase()}</div>
      </div>
      <div className="form-rejilla">
        <Campo etiqueta="Idioma original">
          <select className="entrada" value={origen} onChange={(e) => setOrigen(e.target.value)}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </Campo>
        <Campo etiqueta="Traducir a">
          <select className="entrada" value={destino} onChange={(e) => setDestino(e.target.value)}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </Campo>
        <Campo etiqueta="Páginas" ayuda={`Vacío = todas (${doc.paginas}). Ejemplo: 1-5, 8. Puedes añadir más páginas después.`} ancho>
          <input className="entrada mono" placeholder="todas" value={rango} onChange={(e) => setRango(e.target.value)} />
        </Campo>
      </div>
      {resumen?.id && (
        <div className="chips">
          <span className="chip verde">{segs.ok || 0} traducidos</span>
          {segs.error ? <span className="chip rojo">{segs.error} con error</span> : null}
          {segs.pendiente ? <span className="chip acido">{segs.pendiente} pendientes</span> : null}
          <span className="chip">{resumen.paginas?.length || 0} páginas analizadas</span>
        </div>
      )}
      <Casilla checked={reintentar} onChange={setReintentar}>Reintentar los párrafos que fallaron antes</Casilla>
      <Campo etiqueta={`Glosarios ${IDIOMAS_UI[origen]} → ${IDIOMAS_UI[destino]}`} ayuda="Los términos que aparezcan en cada párrafo se envían al modelo como terminología obligatoria.">
        <div className="chips">
          {glosarios.length === 0 && <span className="tenue">No hay glosarios para este par de idiomas.</span>}
          {glosarios.map((g) => (
            <button key={g.id} type="button" className={`chip ${activos.includes(g.id) ? 'on' : ''}`}
              onClick={() => setActivos((a) => a.includes(g.id) ? a.filter((x) => x !== g.id) : [...a, g.id])}>
              {activos.includes(g.id) && <Check size={11} />}{g.nombre} · {g.n}
            </button>
          ))}
        </div>
      </Campo>
    </Modal>
  )
}

export function ModalExportar({ doc, destino, onCerrar }) {
  const avisar = useAviso()
  const [hecho, setHecho] = useState(null)
  const [ocupado, setOcupado] = useState(null)
  const hayTrad = doc?.traducciones?.some((t) => t.destino === destino)
  const exportar = async (tipo) => {
    setOcupado(tipo)
    try { setHecho(await api.post(`/api/documentos/${doc.id}/exportar`, { tipo, destino })) }
    catch (e) { avisar(e.message, 'error') } finally { setOcupado(null) }
  }
  const guardarComo = async () => {
    const r = await dialogoNativo('guardar', { nombre: hecho.nombre })
    if (r === null) return window.open(`/api/archivo?ruta=${encodeURIComponent(hecho.ruta)}`)
    if (!r.length) return
    await api.post('/api/copiar-a', { origen: hecho.ruta, destino: r[0] })
    avisar('Guardado en ' + r[0], 'ok')
  }
  const opciones = [
    { tipo: 'traducido', titulo: 'PDF traducido', desc: 'Mismo diseño, texto traducido seleccionable y buscable.', trad: true },
    { tipo: 'bilingue_lado', titulo: 'Bilingüe lado a lado', desc: 'Cada página: original a la izquierda, traducción a la derecha.', trad: true },
    { tipo: 'bilingue_intercalado', titulo: 'Bilingüe intercalado', desc: 'Página original seguida de su traducción.', trad: true },
    { tipo: 'anotado', titulo: 'PDF anotado', desc: 'Original con tus resaltados, subrayados y notas como anotaciones PDF.' },
    { tipo: 'markdown', titulo: 'Notas en Markdown', desc: 'Todas las notas y citas en un archivo .md.' },
  ]
  return (
    <Modal titulo="Exportar" onCerrar={onCerrar}>
      <div className="col">
        {opciones.map((o) => (
          <div key={o.tipo} className="fila" style={{ border: '2px solid var(--tinta)', padding: '10px 12px', background: 'var(--papel-3)' }}>
            <div style={{ flex: 1 }}><b>{o.titulo}</b><div className="tenue" style={{ fontSize: 12.5 }}>{o.desc}</div></div>
            <button className="btn chico" disabled={(o.trad && !hayTrad) || ocupado} onClick={() => exportar(o.tipo)}>
              <Download size={13} />{ocupado === o.tipo ? 'Generando…' : o.trad && !hayTrad ? 'Sin traducción' : 'Generar'}
            </button>
          </div>
        ))}
      </div>
      {hecho && (
        <div className="aviso-legal">
          <b>Listo:</b> <span className="mono" style={{ fontSize: 11.5, wordBreak: 'break-all' }}>{hecho.ruta}</span>
          <div className="fila" style={{ marginTop: 10 }}>
            <button className="btn chico negro" onClick={() => abrirRuta(hecho.ruta)}><ExternalLink size={13} />Abrir</button>
            <button className="btn chico" onClick={() => abrirRuta(hecho.ruta, true)}><FolderOpen size={13} />Mostrar en carpeta</button>
            <button className="btn chico primario" onClick={guardarComo}><Save size={13} />Guardar como…</button>
          </div>
        </div>
      )}
    </Modal>
  )
}

export function ModalTermino({ texto, docId, destino, onCerrar, onRetraducido }) {
  const avisar = useAviso()
  const [glosarios, setGlosarios] = useState([])
  const [gid, setGid] = useState('')
  const [origen, setOrigen] = useState(texto.slice(0, 120))
  const [trad, setTrad] = useState('')
  const [retraducir, setRetraducir] = useState(!!destino)
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    api.get('/api/glosarios').then((g) => {
      const propios = g.filter((x) => !x.integrado)
      setGlosarios(g)
      setGid(String((propios[0] || g[0])?.id || ''))
    })
  }, [])
  const guardar = async () => {
    if (!origen.trim() || !trad.trim()) return avisar('Escribe el término y su traducción.', 'error')
    setOcupado(true)
    try {
      let id = gid
      if (id === 'nuevo') id = (await api.post('/api/glosarios', { nombre: 'Mis términos', origen: 'en', destino: destino || 'es' })).id
      await api.post(`/api/glosarios/${id}/termino`, { origen, destino: trad })
      const g = glosarios.find((x) => String(x.id) === String(id))
      if (g) {
        const aj = await api.get('/api/ajustes')
        const act = new Set(aj.traduccion.glosarios_activos || []); act.add(g.id)
        await api.put('/api/ajustes', { traduccion: { glosarios_activos: [...act] } })
      }
      avisar('Término añadido al glosario.', 'ok')
      if (retraducir && destino) {
        avisar('Retraduciendo solo los párrafos que contienen el término…')
        const r = await api.post(`/api/documentos/${docId}/retraducir-termino`, { destino, termino: origen })
        avisar(`${r.segmentos} párrafos retraducidos.`, 'ok')
        onRetraducido()
      }
      onCerrar()
    } catch (e) { avisar(e.message, 'error') } finally { setOcupado(false) }
  }
  return (
    <Modal titulo="Añadir al glosario" onCerrar={onCerrar} pie={<>
      <button className="btn" onClick={onCerrar}>Cancelar</button>
      <button className="btn primario" onClick={guardar} disabled={ocupado}><BookA size={15} />{ocupado ? 'Guardando…' : 'Guardar término'}</button>
    </>}>
      <div className="form-rejilla">
        <Campo etiqueta="Término original"><input className="entrada" value={origen} onChange={(e) => setOrigen(e.target.value)} /></Campo>
        <Campo etiqueta="Traducción obligatoria"><input autoFocus className="entrada" value={trad} onChange={(e) => setTrad(e.target.value)} /></Campo>
        <Campo etiqueta="Glosario" ancho>
          <select className="entrada" value={gid} onChange={(e) => setGid(e.target.value)}>
            {glosarios.map((g) => <option key={g.id} value={g.id}>{g.nombre} ({g.origen}→{g.destino}){g.integrado ? ' · integrado' : ''}</option>)}
            <option value="nuevo">+ Crear «Mis términos»</option>
          </select>
        </Campo>
      </div>
      {destino && <Casilla checked={retraducir} onChange={setRetraducir}>Retraducir ahora solo los párrafos que contienen este término</Casilla>}
    </Modal>
  )
}

export function PanelSegmento({ seg, docId, destino, onCerrar, onCambio, onTermino }) {
  const avisar = useAviso()
  const [texto, setTexto] = useState(seg.traducido || '')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => { setTexto(seg.traducido || '') }, [seg])
  const guardar = async () => {
    setOcupado(true)
    try { await api.put(`/api/segmentos/${seg.id}`, { texto }); avisar('Traducción corregida.', 'ok'); onCambio(); onCerrar() }
    catch (e) { avisar(e.message, 'error') } finally { setOcupado(false) }
  }
  const reintentar = async () => {
    setOcupado(true)
    try { const r = await api.post(`/api/segmentos/${seg.id}/reintentar`); setTexto(r.traducido); avisar('Párrafo retraducido.', 'ok'); onCambio() }
    catch (e) { avisar(e.message, 'error') } finally { setOcupado(false) }
  }
  return (
    <div className="caja panel-seg">
      <div className="caja-cab"><span className="num">P.{seg.pagina}·B{seg.bloque}</span>Párrafo
        <span className={`chip ${seg.estado === 'ok' ? 'verde' : seg.estado === 'error' ? 'rojo' : 'acido'}`}>{seg.estado}</span>
        <button className="btn fantasma icono chico" style={{ marginLeft: 'auto' }} onClick={onCerrar}><X size={15} /></button></div>
      <div className="caja-cuerpo col" style={{ overflow: 'auto' }}>
        <div style={{ fontSize: 12.5, background: 'var(--papel-2)', padding: 10, border: '2px solid var(--tinta)', maxHeight: 160, overflow: 'auto' }}>{seg.original}</div>
        {seg.error && <div className="chip rojo" style={{ whiteSpace: 'normal', textTransform: 'none' }}>{seg.error}</div>}
        <textarea className="entrada" rows={6} style={{ fontFamily: 'var(--sans)', fontSize: 13 }} value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Traducción" />
        <div className="fila">
          <button className="btn chico primario" onClick={guardar} disabled={ocupado}><Save size={13} />Guardar</button>
          <button className="btn chico" onClick={reintentar} disabled={ocupado}><RotateCcw size={13} />Retraducir</button>
          <button className="btn chico" onClick={() => { const s = window.getSelection()?.toString().trim(); onTermino(s || seg.original.split(/\s+/).slice(0, 3).join(' ')) }}><BookA size={13} />Término</button>
        </div>
      </div>
    </div>
  )
}

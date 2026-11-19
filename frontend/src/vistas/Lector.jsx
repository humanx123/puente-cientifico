import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ZoomIn, ZoomOut, Languages, Download, PanelLeft, MessageSquare, Image as ImgIcon, ListTree, Search, StickyNote,
  Highlighter, Underline, Copy, BookA, Bookmark, Trash2, ChevronLeft, ChevronRight, Square, Maximize2, Library,
} from 'lucide-react'
import { api, qs, IDIOMAS_UI } from '../api.js'
import { Cabecera, PanelLateral, Progreso, useAviso, Vacio } from '../ui.jsx'
import Pagina from './Pagina.jsx'
import Asistente from './Asistente.jsx'
import { ModalTraducir, ModalExportar, ModalTermino, PanelSegmento } from './LectorModales.jsx'

const COLORES = { amarillo: '#ffe600', verde: '#7dff7a', rosa: '#ff7ad9', azul: '#7ad7ff' }

export default function Lector({ doc, abrirDoc, irA, ajustes, trabajos, refrescar }) {
  const avisar = useAviso()
  const [info, setInfo] = useState(null)
  const [paginas, setPaginas] = useState([])
  const [zoom, setZoom] = useState(() => Number(localStorage.getItem('pc.zoom')) || 1.25)
  const [modo, setModo] = useState('original')
  const [destino, setDestino] = useState(ajustes?.traduccion?.idioma_destino || 'es')
  const [pag, setPag] = useState(1)
  const [visibles, setVisibles] = useState(() => new Set([1, 2]))
  const [lateral, setLateral] = useState('miniaturas')
  const [lateralAbierto, setLateralAbierto] = useState(true)
  const [asistente, setAsistente] = useState(false)
  const [indice, setIndice] = useState([])
  const [notas, setNotas] = useState([])
  const [resaltes, setResaltes] = useState({})
  const [segs, setSegs] = useState({})
  const [busq, setBusq] = useState('')
  const [hits, setHits] = useState([])
  const [hitIdx, setHitIdx] = useState(0)
  const [sel, setSel] = useState(null)
  const [modal, setModal] = useState(null)
  const [segActivo, setSegActivo] = useState(null)
  const [seleccionAsistente, setSeleccionAsistente] = useState(null)
  const [sello, setSello] = useState(0)
  const [recientes, setRecientes] = useState([])
  const visorRef = useRef(null)
  const filasRef = useRef({})
  const guardarPag = useRef(null)

  const id = doc?.id
  const trabajo = trabajos.find((t) => t.documento_id === id && ['preparando', 'en_curso'].includes(t.estado))
  const trad = info?.traducciones?.find((t) => t.destino === destino)
  const hayTrad = !!trad

  const cargarInfo = useCallback(async () => {
    if (!id) return
    const d = await api.get(`/api/documentos/${id}`)
    setInfo(d)
    return d
  }, [id])

  useEffect(() => {
    if (!id) { api.get('/api/documentos?vista=recientes').then((r) => setRecientes(r.slice(0, 8))).catch(() => {}); return }
    let vivo = true
    setInfo(null); setPaginas([]); setSegs({}); setResaltes({}); setHits([]); setBusq('')
    ;(async () => {
      try {
        const [d, p, ind, n] = await Promise.all([
          api.get(`/api/documentos/${id}`), api.get(`/api/documentos/${id}/paginas`),
          api.get(`/api/documentos/${id}/indice`), api.get(`/api/documentos/${id}/notas`),
        ])
        if (!vivo) return
        setInfo(d); setPaginas(p); setIndice(ind); setNotas(n)
        const t = d.traducciones.find((x) => x.destino === (ajustes?.traduccion?.idioma_destino || 'es')) || d.traducciones[0]
        if (t) { setDestino(t.destino); setModo('comparar') } else setModo('original')
        api.post(`/api/documentos/${id}/abierto`).catch(() => {})
        const destinoPag = doc.pagina || d.pagina_actual || 1
        setTimeout(() => irAPagina(destinoPag, false), 120)
      } catch (e) { avisar(e.message, 'error') }
    })()
    return () => { vivo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, doc?.t])

  useEffect(() => { localStorage.setItem('pc.zoom', zoom) }, [zoom])

  // Mientras se traduce, refrescar las imágenes traducidas cada ~8 s
  const hechos = trabajo?.segmentos_hechos
  useEffect(() => {
    if (!trabajo) return
    const t = setTimeout(() => { setSello(Date.now()); setSegs({}); cargarInfo() }, 8500)
    return () => clearTimeout(t)
  }, [hechos, trabajo, cargarInfo])
  const ultimoTrabajo = trabajos.find((t) => t.documento_id === id)
  const estadoUltimo = ultimoTrabajo?.estado
  useEffect(() => {
    if (estadoUltimo && !['preparando', 'en_curso'].includes(estadoUltimo)) {
      setSello(Date.now()); setSegs({})
      cargarInfo().then((d) => { if (d?.traducciones?.length && modo === 'original') setModo('comparar') })
      refrescar?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estadoUltimo])

  // Páginas visibles y página actual
  useEffect(() => {
    const raiz = visorRef.current
    if (!raiz || !paginas.length) return
    const obs = new IntersectionObserver((ents) => {
      setVisibles((prev) => {
        const s = new Set(prev)
        ents.forEach((e) => { const n = Number(e.target.dataset.fila); if (e.isIntersecting) { s.add(n); s.add(n + 1) } })
        return s
      })
      const vis = ents.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)
      if (vis[0]) {
        const n = Number(vis[0].target.dataset.fila)
        setPag(n)
        clearTimeout(guardarPag.current)
        guardarPag.current = setTimeout(() => api.patch(`/api/documentos/${id}`, { pagina_actual: n }).catch(() => {}), 1200)
      }
    }, { root: raiz, rootMargin: '400px 0px', threshold: [0, 0.25, 0.5, 0.75] })
    Object.values(filasRef.current).forEach((el) => el && obs.observe(el))
    return () => obs.disconnect()
  }, [paginas, zoom, modo, id])

  const irAPagina = (n, suave = true) => {
    const el = filasRef.current[n]
    if (el) el.scrollIntoView({ behavior: suave ? 'smooth' : 'auto', block: 'start' })
    setVisibles((s) => new Set([...s, n, n + 1]))
  }

  // Resaltados y segmentos de páginas visibles
  const listaVisibles = useMemo(() => [...visibles].filter((n) => n >= 1 && n <= paginas.length).sort((a, b) => a - b), [visibles, paginas.length])
  const cargarResaltes = useCallback(async (n) => {
    try { const r = await api.get(`/api/documentos/${id}/resaltados/${n}`); setResaltes((x) => ({ ...x, [n]: r })) } catch { /* */ }
  }, [id])
  useEffect(() => {
    if (!id) return
    listaVisibles.forEach((n) => { if (!(n in resaltes)) cargarResaltes(n) })
    if (hayTrad && modo !== 'original') {
      listaVisibles.forEach((n) => {
        if (!(n in segs)) api.get(`/api/documentos/${id}/segmentos/${destino}/${n}`).then((r) => setSegs((x) => ({ ...x, [n]: r }))).catch(() => {})
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listaVisibles, id, hayTrad, modo, destino, segs])
  useEffect(() => { setSegs({}) }, [destino])

  // Selección de texto → menú flotante
  const alSoltar = () => {
    setTimeout(() => {
      const s = window.getSelection()
      const texto = s?.toString().replace(/\s+/g, ' ').trim()
      if (!texto || texto.length < 2) return setSel(null)
      const nodo = s.anchorNode?.parentElement?.closest('.pagina')
      if (!nodo) return setSel(null)
      const r = s.getRangeAt(0).getBoundingClientRect()
      setSel({ texto: texto.slice(0, 1500), pagina: Number(nodo.dataset.pag), variante: nodo.dataset.variante, x: r.left, y: r.top - 46 })
    }, 10)
  }

  const crearNota = async (tipo, extra = {}) => {
    if (!sel && !extra.pagina) return
    try {
      const n = await api.post(`/api/documentos/${id}/notas`, { pagina: sel?.pagina || pag, tipo, cita: sel?.texto || '', ...extra })
      setNotas((x) => [...x, n].sort((a, b) => a.pagina - b.pagina))
      cargarResaltes(n.pagina)
      avisar(tipo === 'resaltado' ? 'Resaltado guardado.' : tipo === 'subrayado' ? 'Subrayado guardado.' : 'Nota guardada.', 'ok')
    } catch (e) { avisar(e.message, 'error') }
    setSel(null); window.getSelection()?.removeAllRanges()
  }

  const borrarNota = async (n) => {
    await api.del(`/api/notas/${n.id}`)
    setNotas((x) => x.filter((y) => y.id !== n.id))
    cargarResaltes(n.pagina)
  }

  const buscar = async (e) => {
    e?.preventDefault()
    if (!busq.trim()) return setHits([])
    try {
      const variante = modo === 'traduccion' && hayTrad ? destino : 'original'
      const r = await api.get(`/api/documentos/${id}/buscar` + qs({ q: busq, variante }))
      setHits(r); setHitIdx(0)
      if (r[0]) irAPagina(r[0].pagina)
      else avisar('Sin coincidencias.', 'info')
    } catch (err) { avisar(err.message, 'error') }
  }
  const hitsPorPagina = useMemo(() => Object.fromEntries(hits.map((h) => [h.pagina, h.rects])), [hits])

  // Atajos de teclado
  useEffect(() => {
    const k = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return
      if (e.ctrlKey && (e.key === '+' || e.key === '=')) { e.preventDefault(); setZoom((z) => Math.min(3, +(z + 0.15).toFixed(2))) }
      if (e.ctrlKey && e.key === '-') { e.preventDefault(); setZoom((z) => Math.max(0.4, +(z - 0.15).toFixed(2))) }
      if (e.ctrlKey && e.key.toLowerCase() === 'f') { e.preventDefault(); setLateral('buscar'); setLateralAbierto(true) }
      if (e.key === 'PageDown') irAPagina(Math.min(paginas.length, pag + 1))
      if (e.key === 'PageUp') irAPagina(Math.max(1, pag - 1))
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  })

  if (!id) {
    return (
      <>
        <Cabecera eti="// lector" titulo="Ningún documento abierto" />
        <div className="cuerpo cuerpo-pad">
          <Vacio titulo="Abre un PDF">
            <p style={{ margin: 0 }}>Elige un documento en la biblioteca para leer, traducir con maquetación, anotar y preguntar al asistente.</p>
            <button className="btn primario" onClick={() => irA('biblioteca')}><Library size={16} />Ir a la biblioteca</button>
          </Vacio>
          {recientes.length > 0 && (
            <div className="caja" style={{ marginTop: 24 }}>
              <div className="caja-cab"><span className="num">//</span>Leídos recientemente</div>
              {recientes.map((d) => <div key={d.id} className="res-global" style={{ border: 0, borderBottom: '2px solid var(--tinta)' }} onClick={() => abrirDoc(d.id, d.pagina_actual)}><b>{d.titulo}</b><span className="mono tenue" style={{ fontSize: 11 }}>P. {d.pagina_actual} / {d.paginas}</span></div>)}
            </div>
          )}
        </div>
      </>
    )
  }

  const anchoBase = (p) => p.w * zoom
  const mostrarOriginal = modo !== 'traduccion'
  const mostrarTrad = modo !== 'original'
  const progreso = trabajo ? Math.round(100 * (trabajo.segmentos_hechos / Math.max(1, trabajo.segmentos_total))) : 0

  return (
    <>
      <Cabecera eti={`// lector · ${info?.autores?.slice(0, 80) || 'documento'}${info?.anio ? ' · ' + info.anio : ''}${info?.doi ? ' · doi ' + info.doi : ''}`} titulo={info?.titulo || 'Cargando…'} mediano>
        <div className="fila">
          <button className="btn primario" onClick={() => setModal('traducir')}><Languages size={16} />{hayTrad ? 'Traducir más' : 'Traducir'}</button>
          <button className="btn" onClick={() => setModal('exportar')}><Download size={16} />Exportar</button>
          <button className={`btn ${asistente ? 'activo' : 'negro'}`} onClick={() => setAsistente((a) => !a)}><MessageSquare size={16} />Asistente</button>
        </div>
      </Cabecera>

      <div className="barra-lector">
        <button className="btn icono chico" onClick={() => setLateralAbierto((x) => !x)} title="Panel lateral"><PanelLeft size={15} /></button>
        <div className="grupo-btn">
          <button className={`btn chico ${modo === 'original' ? 'activo' : ''}`} onClick={() => setModo('original')}>Original</button>
          <button className={`btn chico ${modo === 'comparar' ? 'activo' : ''}`} onClick={() => setModo('comparar')} disabled={!hayTrad}>Comparar</button>
          <button className={`btn chico ${modo === 'traduccion' ? 'activo' : ''}`} onClick={() => setModo('traduccion')} disabled={!hayTrad}>Traducción</button>
        </div>
        {info?.traducciones?.length > 1 && (
          <select className="entrada" style={{ width: 140, padding: '5px 8px' }} value={destino} onChange={(e) => setDestino(e.target.value)}>
            {info.traducciones.map((t) => <option key={t.destino} value={t.destino}>{IDIOMAS_UI[t.destino] || t.destino}</option>)}
          </select>
        )}
        {hayTrad && <span className={`chip ${trad.estado === 'completa' ? 'verde' : 'acido'}`}>{trad.estado === 'completa' ? 'Traducción completa' : `Traducción ${trad.estado}`}</span>}
        <div className="espaciador" />
        <button className="btn icono chico" onClick={() => irAPagina(Math.max(1, pag - 1))}><ChevronLeft size={15} /></button>
        <span className="mono" style={{ fontSize: 12 }}>
          <input className="entrada mono" style={{ width: 54, padding: '4px 6px', display: 'inline-block', textAlign: 'center' }} value={pag}
            onChange={(e) => setPag(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && irAPagina(Math.max(1, Math.min(paginas.length, Number(pag) || 1)))} /> / {paginas.length}
        </span>
        <button className="btn icono chico" onClick={() => irAPagina(Math.min(paginas.length, pag + 1))}><ChevronRight size={15} /></button>
        <div className="grupo-btn">
          <button className="btn icono chico" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.15).toFixed(2)))}><ZoomOut size={15} /></button>
          <button className="btn chico mono" onClick={() => setZoom(1.25)} style={{ minWidth: 62 }}>{Math.round(zoom * 100)}%</button>
          <button className="btn icono chico" onClick={() => setZoom((z) => Math.min(3, +(z + 0.15).toFixed(2)))}><ZoomIn size={15} /></button>
          <button className="btn icono chico" title="Ajustar al ancho" onClick={() => {
            const w = visorRef.current?.clientWidth || 900
            const p = paginas[0]
            if (p) setZoom(+(((w - 80) / (modo === 'comparar' ? 2 : 1) - 20) / p.w).toFixed(2))
          }}><Maximize2 size={15} /></button>
        </div>
      </div>

      {trabajo && (
        <div style={{ padding: '8px 14px', borderBottom: '3px solid var(--tinta)', background: 'var(--acido)', color: '#0a0a0a', display: 'grid', gridTemplateColumns: '1fr 260px auto', gap: 14, alignItems: 'center' }}>
          <span className="mono" style={{ fontSize: 12, fontWeight: 700 }}>{trabajo.mensaje.toUpperCase()} · {trabajo.segmentos_hechos}/{trabajo.segmentos_total} SEGMENTOS{trabajo.errores ? ` · ${trabajo.errores} ERRORES` : ''}</span>
          <Progreso valor={progreso} />
          <button className="btn chico peligro" onClick={() => api.post(`/api/trabajos/${trabajo.id}/cancelar`)}><Square size={12} />Detener</button>
        </div>
      )}

      <div className="lector" style={{ flex: 1, minHeight: 0 }}>
        {lateralAbierto && <PanelLateral clave="lector" ancho={250} min={170} max={520} titulo="Páginas"><aside className="lateral">
          <div className="pestanas">
            {[['miniaturas', ImgIcon], ['indice', ListTree], ['buscar', Search], ['notas', StickyNote]].map(([k, I]) => (
              <button key={k} className={`pestana ${lateral === k ? 'activo' : ''}`} onClick={() => setLateral(k)} title={k}><I size={16} /></button>
            ))}
          </div>
          <div className="lateral-cuerpo">
            {lateral === 'miniaturas' && paginas.map((p) => (
              <div key={p.n} className={`miniatura ${pag === p.n ? 'activo' : ''}`} onClick={() => irAPagina(p.n)}>
                <img loading="lazy" src={`/api/documentos/${id}/pagina/${p.n}.png?zoom=0.3`} alt="" />
                <span className="n">{p.n}</span>
              </div>
            ))}
            {lateral === 'indice' && (indice.length ? indice.map((t, i) => (
              <button key={i} className="toc-item" style={{ paddingLeft: 4 + (t.nivel - 1) * 14 }} onClick={() => irAPagina(t.pagina)}>
                {t.titulo} <span className="mono tenue" style={{ fontSize: 10 }}>{t.pagina}</span>
              </button>
            )) : <div className="tenue">Este PDF no tiene índice.</div>)}
            {lateral === 'buscar' && (
              <div className="col">
                <form onSubmit={buscar} className="busqueda"><Search size={15} /><input autoFocus className="entrada" placeholder="Buscar en el documento" value={busq} onChange={(e) => setBusq(e.target.value)} /></form>
                {hits.length > 0 && (
                  <div className="fila">
                    <span className="mono" style={{ fontSize: 11 }}>{hitIdx + 1}/{hits.length} PÁGINAS</span>
                    <button className="btn icono chico" onClick={() => { const i = (hitIdx - 1 + hits.length) % hits.length; setHitIdx(i); irAPagina(hits[i].pagina) }}><ChevronLeft size={14} /></button>
                    <button className="btn icono chico" onClick={() => { const i = (hitIdx + 1) % hits.length; setHitIdx(i); irAPagina(hits[i].pagina) }}><ChevronRight size={14} /></button>
                  </div>
                )}
                {hits.map((h, i) => (
                  <div key={i} className="res-global" style={{ fontSize: 12 }} onClick={() => { setHitIdx(i); irAPagina(h.pagina) }}>
                    <span className="chip">P. {h.pagina} · {h.rects.length}×</span><span>…{h.contexto}…</span>
                  </div>
                ))}
              </div>
            )}
            {lateral === 'notas' && (
              <div className="col">
                <div className="fila">
                  <button className="btn chico" onClick={() => { const t = prompt(`Nota para la página ${pag}:`); t && crearNota('nota', { pagina: pag, texto: t, cita: '' }) }}><StickyNote size={13} />Nota P. {pag}</button>
                  <button className="btn chico" onClick={() => crearNota('marcador', { pagina: pag, texto: `Marcador página ${pag}`, cita: '' })}><Bookmark size={13} />Marcador</button>
                </div>
                {notas.length === 0 && <div className="tenue" style={{ fontSize: 12 }}>Selecciona texto en la página para resaltar, subrayar o anotar.</div>}
                {notas.map((n) => (
                  <div key={n.id} className="res-global" onClick={() => irAPagina(n.pagina)} style={{ borderLeft: `8px solid ${n.color}` }}>
                    <div className="fila"><span className="chip">P. {n.pagina}</span><span className="chip">{n.tipo}</span>
                      <button className="btn fantasma icono chico" style={{ marginLeft: 'auto' }} onClick={(e) => { e.stopPropagation(); borrarNota(n) }}><Trash2 size={13} /></button></div>
                    {n.cita && <div style={{ fontSize: 12, fontStyle: 'italic' }}>«{n.cita.slice(0, 220)}»</div>}
                    {n.texto && <div style={{ fontSize: 12.5, whiteSpace: 'pre-wrap' }}>{n.texto.slice(0, 600)}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside></PanelLateral>}

        <div className="visor" style={{ flex: 1 }} ref={visorRef} onMouseUp={alSoltar} onScroll={() => sel && setSel(null)}>
          <div className="paginas">
            {paginas.map((p) => {
              const ancho = anchoBase(p)
              const alto = p.h * zoom
              const visible = visibles.has(p.n)
              return (
                <div key={p.n} className="fila-pag" data-fila={p.n} ref={(el) => { filasRef.current[p.n] = el }}>
                  {mostrarOriginal && (
                    <Pagina docId={id} n={p.n} ancho={ancho} alto={alto} zoom={zoom} variante="original" visible={visible}
                      resaltes={resaltes[p.n] || []} busqueda={modo !== 'traduccion' ? hitsPorPagina[p.n] || [] : []} etiqueta={modo === 'comparar' ? `P. ${p.n} · ORIGINAL` : null} />
                  )}
                  {mostrarTrad && hayTrad && (
                    <Pagina docId={id} n={p.n} ancho={ancho} alto={alto} zoom={zoom} variante={destino} visible={visible} sello={sello}
                      busqueda={modo === 'traduccion' ? hitsPorPagina[p.n] || [] : []} segmentos={segs[p.n] || []}
                      onSegmento={setSegActivo} etiqueta={`P. ${p.n} · ${(IDIOMAS_UI[destino] || destino).toUpperCase()}`} />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {asistente && (
          <PanelLateral clave="asistente" lado="der" ancho={380} min={280} max={760} titulo="Asistente">
            <Asistente docId={id} pagina={pag} irAPagina={irAPagina} seleccion={seleccionAsistente} limpiarSeleccion={() => setSeleccionAsistente(null)}
              onNota={(n) => setNotas((x) => [...x, n])} onCerrar={() => setAsistente(false)} />
          </PanelLateral>
        )}
      </div>

      {sel && (
        <div className="menu-seleccion" style={{ left: Math.max(8, Math.min(sel.x, window.innerWidth - 640)), top: Math.max(8, sel.y) }} onMouseDown={(e) => e.preventDefault()}>
          {Object.entries(COLORES).map(([k, c]) => (
            <button key={k} title={`Resaltar ${k}`} onClick={() => crearNota('resaltado', { color: c })}><Highlighter size={14} color={c} />{k === 'amarillo' ? 'Resaltar' : ''}</button>
          ))}
          <button onClick={() => crearNota('subrayado', { color: '#ff3d00' })}><Underline size={14} />Subrayar</button>
          <button onClick={() => { const t = prompt('Tu nota sobre la selección:'); t !== null && crearNota('nota', { texto: t }) }}><StickyNote size={14} />Nota</button>
          <button onClick={() => { setSeleccionAsistente({ texto: sel.texto, pagina: sel.pagina }); setAsistente(true); setSel(null) }}><MessageSquare size={14} />Preguntar</button>
          <button onClick={() => { setModal({ tipo: 'termino', texto: sel.texto }); setSel(null) }}><BookA size={14} />Glosario</button>
          <button onClick={() => { navigator.clipboard.writeText(sel.texto); avisar('Copiado.', 'ok'); setSel(null) }}><Copy size={14} /></button>
        </div>
      )}

      {segActivo && <PanelSegmento seg={segActivo} docId={id} destino={destino} onCerrar={() => setSegActivo(null)}
        onCambio={() => { setSello(Date.now()); setSegs((x) => { const y = { ...x }; delete y[segActivo.pagina]; return y }) }}
        onTermino={(t) => setModal({ tipo: 'termino', texto: t })} />}
      {modal === 'traducir' && <ModalTraducir doc={info} ajustes={ajustes} trabajo={trabajo} onCerrar={() => setModal(null)}
        onIniciado={(d) => { setDestino(d); setModal(null) }} />}
      {modal === 'exportar' && <ModalExportar doc={info} destino={destino} onCerrar={() => setModal(null)} />}
      {modal?.tipo === 'termino' && <ModalTermino texto={modal.texto} docId={id} destino={hayTrad ? destino : null} onCerrar={() => setModal(null)}
        onRetraducido={() => { setSello(Date.now()); setSegs({}) }} />}
    </>
  )
}

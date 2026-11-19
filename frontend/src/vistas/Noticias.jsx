import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Search, Bookmark, BookmarkCheck, Eye, EyeOff, ExternalLink, Rss, Plus, Trash2, FlaskConical, Loader2 } from 'lucide-react'
import { api, abrirUrl, qs } from '../api.js'
import { Cabecera, Campo, Casilla, Modal, useAviso, Vacio } from '../ui.jsx'

export default function Noticias({ estado }) {
  const avisar = useAviso()
  const [items, setItems] = useState([])
  const [facetas, setFacetas] = useState({ nivel: [], area: [], categoria: [] })
  const [filtro, setFiltro] = useState({ nivel: '', area: '', categoria: '', fuente: '', q: '', guardadas: false, no_leidas: false })
  const [fuentes, setFuentes] = useState([])
  const [gestor, setGestor] = useState(false)
  const [actualizando, setActualizando] = useState(false)

  const cargar = useCallback(async () => {
    try { setItems(await api.get('/api/noticias' + qs(filtro))) } catch (e) { avisar(e.message, 'error') }
  }, [filtro, avisar])
  const cargarFuentes = () => api.get('/api/noticias/fuentes').then(setFuentes).catch(() => {})
  useEffect(() => { api.get('/api/noticias/facetas').then(setFacetas); cargarFuentes() }, [])
  useEffect(() => { cargar() }, [cargar, estado?.ultima])

  const actualizar = async () => {
    setActualizando(true)
    try {
      const r = await api.post('/api/noticias/actualizar')
      const res = r.resultado
      avisar(res ? `${res.nuevos} nuevas · ${res.ok} fuentes OK${res.fallidas.length ? ` · fallaron: ${res.fallidas.join(', ')}` : ''}` : 'Actualización en curso…', res?.fallidas?.length ? 'info' : 'ok')
      cargar(); cargarFuentes()
    } catch (e) { avisar(e.message, 'error') } finally { setActualizando(false) }
  }

  const marcar = async (n, cambios) => {
    await api.patch(`/api/noticias/${n.uid}`, cambios)
    setItems((xs) => xs.map((x) => x.uid === n.uid ? { ...x, ...Object.fromEntries(Object.entries(cambios).map(([k, v]) => [k, v ? 1 : 0])) } : x))
  }
  const abrir = (n) => { abrirUrl(n.enlace); if (!n.leida) marcar(n, { leida: true }) }
  const set = (k, v) => setFiltro((f) => ({ ...f, [k]: f[k] === v ? '' : v }))
  const titular = items.slice(0, 6).map((n) => `${n.organizacion.toUpperCase()}: ${n.titulo}`).join('   ///   ')

  return (
    <>
      <Cabecera eti={`// noticias · ${fuentes.filter((f) => f.activa).length} fuentes activas · actualiza cada ${3} h`} titulo="Noticias y convocatorias">
        <div className="fila">
          <button className="btn" onClick={() => setGestor(true)}><Rss size={15} />Fuentes</button>
          <button className="btn primario" onClick={actualizar} disabled={actualizando || estado?.en_curso}>
            <RefreshCw size={15} className={actualizando || estado?.en_curso ? 'girar' : ''} />{actualizando || estado?.en_curso ? 'Actualizando…' : 'Actualizar ahora'}
          </button>
        </div>
      </Cabecera>
      {titular && <div className="marquesina"><div>{titular}</div></div>}
      <div className="noticias" style={{ flex: 1, minHeight: 0 }}>
        <aside className="filtros" style={{ padding: '6px 0' }}>
          <div className="faceta">
            <div className="busqueda" style={{ marginTop: 10 }}><Search size={15} /><input className="entrada" placeholder="Buscar" value={filtro.q} onChange={(e) => setFiltro({ ...filtro, q: e.target.value })} /></div>
            <div className="col" style={{ marginTop: 12, gap: 8 }}>
              <Casilla checked={filtro.no_leidas} onChange={(v) => setFiltro({ ...filtro, no_leidas: v })}>Solo no leídas</Casilla>
              <Casilla checked={filtro.guardadas} onChange={(v) => setFiltro({ ...filtro, guardadas: v })}>Solo guardadas</Casilla>
            </div>
          </div>
          {[['categoria', 'Categoría'], ['area', 'Área'], ['nivel', 'Nivel']].map(([k, t]) => (
            <div key={k} className="faceta">
              <h4>{t}</h4>
              <div className="chips">{facetas[k].map((v) => <button key={v} className={`chip ${filtro[k] === v ? 'on' : ''}`} onClick={() => set(k, v)}>{v}</button>)}</div>
            </div>
          ))}
          <div className="faceta">
            <h4>Fuente</h4>
            <select className="entrada" value={filtro.fuente} onChange={(e) => setFiltro({ ...filtro, fuente: e.target.value })}>
              <option value="">Todas</option>
              {fuentes.map((f) => <option key={f.id} value={f.id}>{f.nombre} ({f.n})</option>)}
            </select>
          </div>
        </aside>
        <div className="cuerpo cuerpo-pad">
          <div className="mono" style={{ fontSize: 12, marginBottom: 14 }}>{items.length} ELEMENTOS</div>
          {items.length === 0 ? (
            <Vacio titulo={estado?.en_curso ? 'Recolectando…' : 'Sin noticias con estos filtros'}>
              <p style={{ margin: 0 }}>La app recoge noticias, convocatorias, becas y olimpiadas de ciencia en español al iniciar y cada pocas horas.</p>
              <button className="btn primario" onClick={actualizar}><RefreshCw size={15} />Actualizar ahora</button>
            </Vacio>
          ) : (
            <div className="columna-noticias">
              {items.map((n) => (
                <article key={n.uid} className={`noticia ${n.leida ? 'leida' : ''}`}>
                  <div className="org"><b>{n.organizacion}</b><span className="tenue">{n.fecha ? new Date(n.fecha + 'T12:00:00').toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' }) : ''}</span></div>
                  <h3 onClick={() => abrir(n)}>{n.titulo}</h3>
                  {n.resumen && <p>{n.resumen}</p>}
                  <div className="chips">
                    {n.categoria.map((c) => <span key={c} className={`chip ${c.startsWith('Convoc') ? 'senal' : c.startsWith('Olimp') ? 'acido' : ''}`}>{c}</span>)}
                    {n.area.filter((a) => a !== 'Otras áreas').map((a) => <span key={a} className="chip">{a}</span>)}
                  </div>
                  <div className="fila">
                    <button className="btn chico negro" onClick={() => abrir(n)}><ExternalLink size={12} />Leer</button>
                    <button className="btn chico" onClick={() => marcar(n, { guardada: !n.guardada })}>{n.guardada ? <BookmarkCheck size={12} /> : <Bookmark size={12} />}{n.guardada ? 'Guardada' : 'Guardar'}</button>
                    <button className="btn chico fantasma" onClick={() => marcar(n, { leida: !n.leida })} title={n.leida ? 'Marcar como no leída' : 'Marcar como leída'}>{n.leida ? <EyeOff size={12} /> : <Eye size={12} />}</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
      {gestor && <GestorFuentes fuentes={fuentes} recargar={cargarFuentes} onCerrar={() => setGestor(false)} />}
    </>
  )
}

const VACIA = { nombre: '', organizacion: '', url: '', tipo: 'rss', base_url: '', selectores: { lista: '', titulo: '', enlace: '', fecha: '' }, etiquetas: { nivel: [], area: [], categoria: [] } }

function GestorFuentes({ fuentes, recargar, onCerrar }) {
  const avisar = useAviso()
  const [nueva, setNueva] = useState(VACIA)
  const [prueba, setPrueba] = useState(null)
  const [probando, setProbando] = useState(false)
  const probar = async () => {
    setProbando(true)
    try { setPrueba(await api.post('/api/noticias/fuentes/probar', nueva)) } catch (e) { avisar(e.message, 'error'); setPrueba(null) } finally { setProbando(false) }
  }
  const guardar = async () => {
    try { await api.post('/api/noticias/fuentes', nueva); avisar('Fuente añadida.', 'ok'); setNueva(VACIA); setPrueba(null); recargar() } catch (e) { avisar(e.message, 'error') }
  }
  const sel = (k, v) => setNueva({ ...nueva, selectores: { ...nueva.selectores, [k]: v } })
  return (
    <Modal titulo="Fuentes de noticias" onCerrar={onCerrar} ancho>
      <table className="tabla">
        <thead><tr><th>Activa</th><th>Fuente</th><th>Tipo</th><th>Último estado</th><th>Nº</th><th></th></tr></thead>
        <tbody>
          {fuentes.map((f) => (
            <tr key={f.id}>
              <td style={{ padding: '6px 10px' }}><Casilla checked={!!f.activa} onChange={(v) => api.post(`/api/noticias/fuentes/${f.id}/activa`, { activa: v }).then(recargar)} /></td>
              <td style={{ padding: '6px 10px' }}><b>{f.nombre}</b><div className="mono tenue" style={{ fontSize: 10.5, wordBreak: 'break-all' }}>{f.url.slice(0, 80)}</div></td>
              <td style={{ padding: '6px 10px' }}><span className="chip">{f.tipo}</span></td>
              <td style={{ padding: '6px 10px', fontSize: 12 }} className={f.ultimo_estado.startsWith('error') ? '' : 'tenue'}>{f.ultimo_estado || '—'}</td>
              <td style={{ padding: '6px 10px' }} className="mono">{f.n}</td>
              <td style={{ padding: '6px 10px' }}><button className="btn chico fantasma" onClick={() => confirm(`¿Quitar «${f.nombre}»?`) && api.del(`/api/noticias/fuentes/${f.id}`).then(recargar)}><Trash2 size={13} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="caja">
        <div className="caja-cab"><Plus size={15} />Añadir fuente</div>
        <div className="caja-cuerpo form-rejilla">
          <Campo etiqueta="Nombre"><input className="entrada" value={nueva.nombre} onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })} placeholder="Ej. Agencia SINC" /></Campo>
          <Campo etiqueta="Organización"><input className="entrada" value={nueva.organizacion} onChange={(e) => setNueva({ ...nueva, organizacion: e.target.value })} /></Campo>
          <Campo etiqueta="Tipo">
            <select className="entrada" value={nueva.tipo} onChange={(e) => setNueva({ ...nueva, tipo: e.target.value })}><option value="rss">RSS / Atom</option><option value="html">Página HTML (selectores CSS)</option></select>
          </Campo>
          <Campo etiqueta="URL"><input className="entrada mono" value={nueva.url} onChange={(e) => setNueva({ ...nueva, url: e.target.value })} placeholder="https://…" /></Campo>
          {nueva.tipo === 'html' && <>
            <Campo etiqueta="Selector de cada elemento" ayuda="Ej. table.board tbody tr"><input className="entrada mono" value={nueva.selectores.lista} onChange={(e) => sel('lista', e.target.value)} /></Campo>
            <Campo etiqueta="Selector del título"><input className="entrada mono" value={nueva.selectores.titulo} onChange={(e) => sel('titulo', e.target.value)} placeholder="td.title a" /></Campo>
            <Campo etiqueta="Selector del enlace"><input className="entrada mono" value={nueva.selectores.enlace} onChange={(e) => sel('enlace', e.target.value)} placeholder="a[href]" /></Campo>
            <Campo etiqueta="Selector de fecha"><input className="entrada mono" value={nueva.selectores.fecha} onChange={(e) => sel('fecha', e.target.value)} placeholder="td.date" /></Campo>
          </>}
          <div className="fila ancho">
            <button className="btn" onClick={probar} disabled={!nueva.url || probando}>{probando ? <Loader2 size={14} className="girar" /> : <FlaskConical size={14} />}Probar (sin guardar)</button>
            <button className="btn primario" onClick={guardar} disabled={!nueva.url || !nueva.nombre}><Plus size={14} />Guardar fuente</button>
          </div>
          {prueba && (
            <div className="ancho consola" style={{ maxHeight: 220 }}>
              <div className="ok">{prueba.length} elementos encontrados</div>
              {prueba.map((p, i) => <div key={i}>· {p.titulo} <span className="aviso">[{p.etiquetas.categoria.join(', ')}]</span></div>)}
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}

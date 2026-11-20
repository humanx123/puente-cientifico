import { useEffect, useState } from 'react'
import {
  Search, Download, ExternalLink, BookOpen, Unlock, Quote, Trash2, Zap, Loader2, ShieldAlert, ChevronDown,
  User, X, BookMarked, Library as LibIcon, FolderOpen, Shield, ShieldOff, Sparkles,
} from 'lucide-react'
import { api, abrirRuta, abrirUrl, qs } from '../api.js'
import { Cabecera, Campo, Casilla, Modal, PanelLateral, useAviso, usePeriodico, usePref, Vacio } from '../ui.jsx'

const ESTADOS = {
  en_cola: ['EN COLA', ''], buscando: ['BUSCANDO', 'acido'], descargando: ['DESCARGANDO', 'acido'], captcha: ['CAPTCHA', 'senal'],
  ok: ['LISTO', 'verde'], duplicado: ['YA EXISTÍA', 'azul'], error: ['ERROR', 'rojo'], verificando: ['VERIFICANDO', 'senal'],
}
const IDIOMAS_LIB = [['', 'Todos los idiomas'], ['es', 'Español'], ['en', 'Inglés'], ['pt', 'Portugués'], ['fr', 'Francés'],
  ['de', 'Alemán'], ['it', 'Italiano'], ['ca', 'Catalán'], ['ru', 'Ruso'], ['zh', 'Chino'], ['ja', 'Japonés'], ['ar', 'Árabe'], ['nl', 'Neerlandés']]
const MODOS = [['todo', 'Todo'], ['titulo', 'Título'], ['autor', 'Autor'], ['titulo_autor', 'Título + autor']]
const TEMAS_LG = [['libros', 'Libros'], ['ficcion', 'Ficción'], ['comics', 'Cómics'], ['revistas', 'Revistas'], ['normas', 'Normas']]
const TIPOS_AA = [['libros', 'No ficción'], ['ficcion', 'Ficción'], ['articulos', 'Artículos'], ['revistas', 'Revistas'], ['comics', 'Cómics'], ['normas', 'Normas']]

// Autor clicable → nueva búsqueda por ese autor
function Autores({ lista, onAutor, max = 8 }) {
  if (!lista?.length) return <span className="tenue">Autoría no disponible</span>
  return lista.slice(0, max).map((a, i) => (
    <span key={i}>{i > 0 && ', '}
      <button className="autor-link" title={`Buscar obras de ${a.nombre || a}`} onClick={() => onAutor(a)}>{a.nombre || a}</button>
    </span>
  ))
}

function TunelChip() {
  const avisar = useAviso()
  const [t, setT] = useState(null)
  usePeriodico(async () => { try { setT(await api.get('/api/tunel')) } catch { /* */ } }, 3000)
  if (!t) return null
  const cambiar = async () => {
    const nuevo = t.modo === 'tor' ? 'directo' : 'tor'
    if (nuevo === 'tor' && !t.disponible) return avisar('Esta instalación no incluye Tor.', 'error')
    await api.put('/api/ajustes', { literatura: { tunel: nuevo } })
    if (nuevo === 'tor') { await api.post('/api/tunel/iniciar').catch((e) => avisar(e.message, 'error')); avisar('Túnel Tor activado para literatura. La primera conexión tarda unos segundos.', 'ok') }
    else { await api.post('/api/tunel/detener'); avisar('Conexión directa.', 'info') }
    setT(await api.get('/api/tunel'))
  }
  const etiqueta = t.modo === 'tor' ? (t.estado === 'listo' ? 'Tor conectado' : t.estado === 'iniciando' ? `Tor ${t.progreso}%` : t.estado === 'error' ? 'Tor con error' : 'Tor en espera')
    : t.modo === 'proxy' ? 'Proxy / VPN' : 'Conexión directa'
  return (
    <button className="btn tunel-chip" onClick={cambiar} title={(t.estado === 'error' ? `Error de Tor: ${t.mensaje}. Usa Ajustes → Diagnóstico → Reparar. ` : '') + 'Activa o desactiva el túnel Tor (solo Sci-Hub, LibGen y Anna\'s Archive)'}>
      <span className={`luz ${t.modo === 'tor' ? t.estado : ''}`} />{t.modo === 'tor' ? <Shield size={14} /> : <ShieldOff size={14} />}{etiqueta}
    </button>
  )
}

// Selección múltiple: casilla por resultado + barra fija con las acciones del lote
function useSeleccion(lista, clave) {
  const [sel, setSel] = useState({})
  useEffect(() => { setSel({}) }, [lista === null]) // nueva búsqueda
  const n = Object.keys(sel).length
  const alternar = (it) => setSel((s) => { const c = { ...s }; const k = it[clave]; if (c[k]) delete c[k]; else c[k] = it; return c })
  const todos = () => setSel(Object.fromEntries((lista || []).map((it) => [it[clave], it])))
  return { sel, n, alternar, todos, limpiar: () => setSel({}), marcado: (it) => !!sel[it[clave]] }
}

function BarraSeleccion({ s, total, children }) {
  if (!total) return null
  return (
    <div className="barra-seleccion">
      <label className="casilla">
        <input type="checkbox" checked={s.n > 0 && s.n >= total} ref={(el) => { if (el) el.indeterminate = s.n > 0 && s.n < total }}
          onChange={(e) => (e.target.checked ? s.todos() : s.limpiar())} />
        {s.n ? `${s.n} seleccionados` : 'Seleccionar todos'}
      </label>
      {s.n > 0 && <button className="btn chico fantasma" onClick={s.limpiar}><X size={12} />Quitar selección</button>}
      <span className="espaciador" />
      {s.n > 0 && children}
    </div>
  )
}

function BarraModo({ modo, setModo, extra = [] }) {
  return (
    <div className="grupo-btn">
      {[...MODOS, ...extra].map(([k, t]) => <button key={k} type="button" className={`btn chico ${modo === k ? 'activo' : ''}`} onClick={() => setModo(k)}>{t}</button>)}
    </div>
  )
}

export default function Literatura({ trabajos, abrirDoc, ajustes }) {
  const avisar = useAviso()
  const [pestana, setPestana] = usePref('lit.pestana', 'articulos')
  const [captcha, setCaptcha] = useState('')
  const [abiertos, setAbiertos] = useState({})

  const descargar = async (consultas, fuente, obra) => {
    try {
      const r = await api.post('/api/literatura/descargar', { consultas, fuente, obra })
      avisar(`${r.length} ${r.length === 1 ? 'descarga añadida' : 'descargas añadidas'} a la cola.`, 'ok')
    } catch (e) { avisar(e.message, 'error') }
  }
  const descargarLibro = async (libro, fuente) => {
    try { await api.post('/api/libgen/descargar', { libro, fuente }); avisar('Libro añadido a la cola de descargas.', 'ok') }
    catch (e) { avisar(e.message, 'error') }
  }
  const pendienteCaptcha = trabajos.find((t) => t.estado === 'captcha')
  const enviarCaptcha = async (respuesta) => {
    try { await api.post(`/api/literatura/trabajos/${pendienteCaptcha.id}/captcha`, { respuesta }); setCaptcha('') }
    catch (e) { avisar(e.message, 'error') }
  }
  const reintentar = (t) => {
    if (t.fuente === 'libgen' || t.fuente === 'annas') return descargarLibro(t.obra, t.fuente)
    return descargar(t.consulta, t.fuente === 'scihub' ? 'auto' : 'scihub', t.obra)
  }

  return (
    <>
      <Cabecera eti="// literatura · openalex · acceso abierto · sci-hub · libgen · anna's archive" titulo="Literatura">
        <div className="fila">
          <TunelChip />
          <div className="grupo-btn">
            <button className={`btn ${pestana === 'articulos' ? 'activo' : ''}`} onClick={() => setPestana('articulos')}><Search size={15} />Artículos</button>
            <button className={`btn ${pestana === 'libros' ? 'activo' : ''}`} onClick={() => setPestana('libros')}><BookMarked size={15} />LibGen</button>
            <button className={`btn ${pestana === 'annas' ? 'activo' : ''}`} onClick={() => setPestana('annas')}><LibIcon size={15} />Anna's Archive</button>
            <button className={`btn ${pestana === 'lote' ? 'activo' : ''}`} onClick={() => setPestana('lote')}><Zap size={15} />Directa</button>
          </div>
        </div>
      </Cabecera>
      <div className="lit" style={{ flex: 1, minHeight: 0 }}>
        <div className="lit-res" style={{ flex: 1, minWidth: 0 }}>
          {pestana === 'articulos' && <Articulos descargar={descargar} />}
          {pestana === 'libros' && <Libros fuente="libgen" descargarLibro={descargarLibro} />}
          {pestana === 'annas' && <Libros fuente="annas" descargarLibro={descargarLibro} />}
          {pestana === 'lote' && <Lote descargar={descargar} ajustes={ajustes} />}
        </div>

        <PanelLateral clave="cola" lado="der" ancho={380} min={260} max={700} titulo="Descargas">
          <div className="cola">
            <div className="caja-cab" style={{ background: 'var(--tinta)', color: 'var(--papel)' }}>
              <span className="num">{trabajos.length}</span>Cola de descargas
              <button className="btn chico" style={{ marginLeft: 'auto' }} onClick={() => api.post('/api/literatura/limpiar')}><Trash2 size={12} />Limpiar</button>
            </div>
            <div style={{ overflow: 'auto', flex: 1 }}>
              {trabajos.length === 0 && <div className="tenue" style={{ padding: 16, fontSize: 13 }}>Las descargas aparecerán aquí con su registro en tiempo real.</div>}
              {trabajos.map((t) => {
                const [txt, cls] = ESTADOS[t.estado] || [t.estado, '']
                const ab = abiertos[t.id] ?? ['captcha', 'error', 'buscando', 'descargando', 'verificando'].includes(t.estado)
                return (
                  <div key={t.id} className="trabajo">
                    <div className="fila" style={{ cursor: 'pointer' }} onClick={() => setAbiertos((a) => ({ ...a, [t.id]: !ab }))}>
                      <span className={`chip ${cls}`}>{['buscando', 'descargando'].includes(t.estado) && <Loader2 size={11} className="girar" />}{txt}</span>
                      <span className="mono" style={{ fontSize: 10.5 }}>{{ libgen: 'LIBGEN', annas: "ANNA'S" }[t.fuente] || t.tipo.toUpperCase()}</span>
                    </div>
                    <b style={{ fontSize: 12.5, wordBreak: 'break-word' }}>{t.obra?.titulo || t.consulta}</b>
                    {ab && <div className="consola">{t.registro.map((l, i) => <div key={i} className={l.nivel}>[{l.t}] {l.msg}</div>)}</div>}
                    <div className="fila">
                      {t.documento_id && <button className="btn chico primario" onClick={() => abrirDoc(t.documento_id)}><BookOpen size={12} />Abrir</button>}
                      {!t.documento_id && t.archivo && <button className="btn chico" onClick={() => abrirRuta(t.archivo, true)}><FolderOpen size={12} />Mostrar archivo</button>}
                      {t.estado === 'error' && t.verificable && <button className="btn chico primario" title="Abre un navegador integrado para superar la verificación y capturar el PDF"
                        onClick={() => api.post(`/api/literatura/trabajos/${t.id}/verificar`).catch((e) => avisar(e.message, 'error'))}><Shield size={12} />Abrir verificación</button>}
                      {t.estado === 'error' && t.pagina_url && <button className="btn chico" onClick={() => abrirUrl(t.pagina_url)}><ExternalLink size={12} />Abrir página</button>}
                      {t.suplemento?.length > 0 && t.suplemento.map((s) => <button key={s.url} className="btn chico fantasma" title="Material suplementario del artículo" onClick={() => abrirUrl(s.url)}><Download size={12} />{s.nombre}</button>)}
                      {t.estado === 'error' && <button className="btn chico" onClick={() => reintentar(t)}>Reintentar</button>}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </PanelLateral>
      </div>

      {pendienteCaptcha && (
        <Modal titulo="Verificación CAPTCHA" onCerrar={() => enviarCaptcha(null)} pie={<>
          <button className="btn" onClick={() => enviarCaptcha(null)}>Cancelar descarga</button>
          <button className="btn primario" onClick={() => enviarCaptcha(captcha)} disabled={!captcha.trim()}>Enviar</button>
        </>}>
          <p style={{ margin: 0 }}>Sci-Hub pide verificación para <b>{pendienteCaptcha.obra?.titulo || pendienteCaptcha.consulta}</b>. Escribe el código de la imagen.</p>
          {pendienteCaptcha.captcha?.imagen && <img src={pendienteCaptcha.captcha.imagen} alt="CAPTCHA" style={{ border: '3px solid var(--tinta)', background: '#fff', maxWidth: '100%', minHeight: 60 }} />}
          <input autoFocus className="entrada mono" style={{ fontSize: 20, letterSpacing: '0.2em' }} value={captcha} onChange={(e) => setCaptcha(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && captcha.trim() && enviarCaptcha(captcha)} />
          {pendienteCaptcha.captcha?.pagina && <button className="btn chico fantasma" onClick={() => abrirUrl(pendienteCaptcha.captcha.pagina)}><ExternalLink size={12} />Abrir la página en el navegador</button>}
        </Modal>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Artículos · OpenAlex
// ---------------------------------------------------------------------------
function Articulos({ descargar }) {
  const avisar = useAviso()
  const [modo, setModo] = usePref('lit.modo', 'todo')
  const [q, setQ] = useState('')
  const [q2, setQ2] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [orden, setOrden] = useState('relevancia')
  const [autor, setAutor] = useState(null) // ficha del autor seleccionado
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [ultima, setUltima] = useState(null)
  const seleccion = useSeleccion(res?.obras || null, 'id')
  const descargarSel = async (fuente) => {
    try {
      const r = await api.post('/api/literatura/descargar', { obras: Object.values(seleccion.sel), fuente })
      avisar(`${r.length} artículos añadidos a la cola.`, 'ok'); seleccion.limpiar()
    } catch (e) { avisar(e.message, 'error') }
  }

  const consultar = async (params, pagina = 1) => {
    setCargando(true)
    try {
      const r = await api.get('/api/literatura/buscar' + qs({ ...params, pagina, abierto, desde, hasta, orden }))
      if (pagina === 1) seleccion.limpiar()
      setRes(pagina === 1 ? r : { ...r, obras: [...(res?.obras || []), ...r.obras] })
      setUltima(params)
      if (r.aviso && pagina === 1) avisar(r.aviso, 'info', 9000)
    } catch (err) { avisar(err.message, 'error') } finally { setCargando(false) }
  }
  const buscarIA = async () => {
    setCargando(true); setAutor(null)
    try {
      const r = await api.post('/api/literatura/buscar-ia', { pregunta: q, abierto })
      seleccion.limpiar(); setRes(r); setUltima(null)
      if (r.aviso) avisar(r.aviso, 'info', 9000)
    } catch (err) { avisar(err.message, 'error', 9000) } finally { setCargando(false) }
  }
  const buscar = (e) => {
    e?.preventDefault()
    if (!q.trim() && !q2.trim()) return
    setAutor(null)
    if (modo === 'ia') buscarIA()
    else if (modo === 'titulo_autor') consultar({ titulo: q, autor: q2 })
    else consultar({ q, modo })
  }
  const porAutor = async (a) => {
    if (a.id) {
      setAutor({ id: a.id, nombre: a.nombre, cargando: true })
      consultar({ autor_id: a.id, autor_nombre: a.nombre })
      try { setAutor(await api.get(`/api/literatura/autor/${a.id}`)) } catch { /* sin ficha */ }
    } else {
      setModo('autor'); setQ(a.nombre || a); setAutor(null); consultar({ q: a.nombre || a, modo: 'autor' })
    }
  }
  useEffect(() => { if (ultima) consultar(ultima) }, [abierto, orden]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <form onSubmit={buscar} className="col" style={{ marginBottom: 20 }}>
        <BarraModo modo={modo} setModo={setModo} extra={[['ia', '✦ Con IA']]} />
        <div className="fila">
          <div className="busqueda" style={{ flex: 1 }}>
            {modo === 'autor' ? <User size={17} /> : modo === 'ia' ? <Sparkles size={17} /> : <Search size={17} />}
            <input autoFocus className="entrada" style={{ fontSize: 16, padding: '12px 12px 12px 36px' }}
              placeholder={{ todo: 'Palabras clave, título o DOI', titulo: 'Título del artículo', autor: 'Nombre del autor (ej. Bruce Alberts)', titulo_autor: 'Título',
                ia: 'Describe lo que buscas, p. ej.: antivirales que inhiban la polimerasa del sarampión, estudios de 2020 en adelante' }[modo]}
              value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {modo === 'titulo_autor' && (
            <div className="busqueda" style={{ flex: 1 }}><User size={17} />
              <input className="entrada" style={{ fontSize: 16, padding: '12px 12px 12px 36px' }} placeholder="Autor" value={q2} onChange={(e) => setQ2(e.target.value)} /></div>
          )}
          <button className="btn primario" style={{ padding: '13px 20px' }} disabled={cargando}>{cargando ? <Loader2 size={16} className="girar" /> : <Search size={16} />}Buscar</button>
        </div>
        <div className="fila">
          <Casilla checked={abierto} onChange={setAbierto}>Solo acceso abierto</Casilla>
          <input className="entrada mono" style={{ width: 90 }} placeholder="Desde" value={desde} onChange={(e) => setDesde(e.target.value.replace(/\D/g, '').slice(0, 4))} />
          <input className="entrada mono" style={{ width: 90 }} placeholder="Hasta" value={hasta} onChange={(e) => setHasta(e.target.value.replace(/\D/g, '').slice(0, 4))} />
          <select className="entrada" style={{ width: 170 }} value={orden} onChange={(e) => setOrden(e.target.value)}>
            <option value="relevancia">Más relevantes</option><option value="citas">Más citados</option><option value="recientes">Más recientes</option>
          </select>
        </div>
      </form>

      {autor && (
        <div className="banda-autor">
          <div className="fila"><User size={16} /><b style={{ fontSize: 16 }}>{autor.nombre}</b>
            {autor.orcid && <button className="autor-link mono" style={{ fontSize: 11 }} onClick={() => abrirUrl(autor.orcid)}>ORCID</button>}
            <button className="btn chico fantasma" style={{ marginLeft: 'auto' }} onClick={() => setAutor(null)}><X size={13} /></button></div>
          {autor.obras != null && <div className="mono" style={{ fontSize: 11.5 }}>{autor.obras} obras · {autor.citas?.toLocaleString('es-MX')} citas · índice h {autor.h ?? '—'}</div>}
          {autor.instituciones?.length > 0 && <div style={{ fontSize: 12.5 }}>{autor.instituciones.join(' · ')}</div>}
          {autor.temas?.length > 0 && <div className="chips">{autor.temas.map((t) => <span key={t} className="chip">{t}</span>)}</div>}
        </div>
      )}

      {res?.plan && (
        <div className="banda-autor">
          <div className="fila"><Sparkles size={16} /><b>Búsqueda con IA</b><span className="mono" style={{ fontSize: 11 }}>{res.modelo}</span></div>
          {res.plan.explicacion && <div style={{ fontSize: 12.5 }}>{res.plan.explicacion}</div>}
          <div className="chips">{res.plan.consultas.map((c) => <span key={c} className="chip">{c}</span>)}
            {res.plan.autor && <span className="chip">autor: {res.plan.autor}</span>}
            {(res.plan.desde || res.plan.hasta) && <span className="chip">{res.plan.desde || '…'}–{res.plan.hasta || '…'}</span>}</div>
        </div>
      )}
      {!res && <Vacio titulo="Busca en 250 millones de obras">
        <p style={{ margin: 0, maxWidth: 560 }}>Metadatos de <b>OpenAlex</b>. Busca por título, por autor o por ambos. Haz clic en cualquier autor de los resultados para ver todas sus obras.</p>
      </Vacio>}
      {res && <div className="fila" style={{ marginBottom: 12 }}>
        <span className="mono" style={{ fontSize: 12 }}>{res.total.toLocaleString('es-MX')} RESULTADOS</span>
        {res.fuente === 'crossref' && <span className="chip azul" title="Resultados de Crossref: gratuitos y sin cupo diario">Fuente: Crossref</span>}
        {res.fuente !== 'crossref' && res.creditos?.restantes && <span className={`chip ${Number(res.creditos.restantes) < 150 ? 'acido' : ''}`} title="Cada búsqueda en OpenAlex gasta créditos; con una clave gratuita el límite es mayor. Las búsquedas repetidas usan caché.">
          Créditos OpenAlex: {res.creditos.restantes}/{res.creditos.limite}</span>}
      </div>}
      <BarraSeleccion s={seleccion} total={res?.obras.length}>
        <button className="btn chico primario" onClick={() => descargarSel('auto')}><Download size={13} />Descargar {seleccion.n}</button>
        <button className="btn chico" onClick={() => descargarSel('abierto')}><Unlock size={13} />Solo acceso abierto</button>
        <button className="btn chico negro" onClick={() => descargarSel('scihub')}><Zap size={13} />Sci-Hub</button>
      </BarraSeleccion>
      {res?.obras.map((o) => (
        <div key={o.id} className={`obra ${seleccion.marcado(o) ? 'marcada' : ''}`}>
          <div className="fila" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
            <label className="casilla" style={{ marginTop: 2 }} title="Seleccionar para descargar en lote">
              <input type="checkbox" checked={seleccion.marcado(o)} onChange={() => seleccion.alternar(o)} /></label>
            <h3 style={{ flex: 1 }}>{o.titulo}</h3>
          </div>
          <div className="autores"><Autores lista={o.autores_det?.length ? o.autores_det : o.autores} onAutor={porAutor} /></div>
          <div className="meta">{[o.anio, o.revista, o.doi && `DOI ${o.doi}`].filter(Boolean).join(' · ')}</div>
          {o.motivo_ia && <div style={{ fontSize: 12.5, display: 'flex', gap: 8, alignItems: 'baseline' }}>
            <span className={`chip ${o.relevancia >= 7 ? 'verde' : o.relevancia >= 4 ? 'acido' : ''}`}>IA {o.relevancia}/10</span><span className="tenue">{o.motivo_ia}</span></div>}
          <div className="chips">
            {o.acceso_abierto && <span className="chip verde"><Unlock size={11} />Acceso abierto{o.estado_oa ? ` · ${o.estado_oa}` : ''}</span>}
            {o.pdf_url && <span className="chip">PDF libre</span>}
            {o.citas != null && <span className="chip"><Quote size={11} />{o.citas} citas</span>}
            {o.tipo && <span className="chip">{o.tipo}</span>}
            {o.en_biblioteca && <span className="chip senal">En tu biblioteca</span>}
          </div>
          <div className="fila">
            <button className="btn chico primario" onClick={() => descargar(o.doi || o.pdf_url || o.titulo, 'auto', o)} disabled={!o.doi && !o.pdf_url}><Download size={13} />Obtener PDF</button>
            {o.pdf_url && <button className="btn chico" onClick={() => descargar(o.doi || o.pdf_url, 'abierto', o)}><Unlock size={13} />Solo acceso abierto</button>}
            {o.doi && <button className="btn chico negro" onClick={() => descargar(o.doi, 'scihub', o)}><Zap size={13} />Sci-Hub</button>}
            {o.pagina_url && <button className="btn chico fantasma" onClick={() => abrirUrl(o.pagina_url)}><ExternalLink size={13} />Página</button>}
          </div>
        </div>
      ))}
      {res?.hay_mas && <button className="btn" onClick={() => consultar(ultima, res.pagina + 1)} disabled={cargando}><ChevronDown size={15} />Cargar más</button>}
    </>
  )
}

// ---------------------------------------------------------------------------
// Libros · LibGen (libgen-api-enhanced) y Anna's Archive
// ---------------------------------------------------------------------------
function Libros({ fuente, descargarLibro }) {
  const avisar = useAviso()
  const esAA = fuente === 'annas'
  const [modo, setModo] = usePref(`${fuente}.modo`, 'todo')
  const [q, setQ] = useState('')
  const [temas, setTemas] = usePref(`${fuente}.temas`, esAA ? [] : ['libros'])
  const [ext, setExt] = useState('')
  const [idioma, setIdioma] = usePref(`${fuente}.idioma`, '')
  const [anio, setAnio] = useState('')
  const [orden, setOrden] = useState('relevancia')
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [ultima, setUltima] = useState(null)
  const seleccion = useSeleccion(res?.lista || null, 'md5')
  const descargarSel = async () => {
    try {
      const r = await api.post('/api/libgen/descargar', { libros: Object.values(seleccion.sel), fuente })
      avisar(`${r.length} libros añadidos a la cola (se descargan uno tras otro).`, 'ok'); seleccion.limpiar()
    } catch (e) { avisar(e.message, 'error') }
  }

  const consultar = async (texto, m, pagina = 1) => {
    if (!texto?.trim()) return
    setCargando(true)
    try {
      const r = esAA
        ? await api.get('/api/annas/buscar' + qs({ q: texto, modo: m, tipos: temas.join(','), extension: ext, idioma, orden, pagina }))
        : await api.get('/api/libgen/buscar' + qs({ q: texto, modo: m, temas: temas.join(','), pagina, extension: ext, idioma, anio }))
      const lista = esAA ? r.resultados : r.libros
      if (pagina === 1) seleccion.limpiar()
      setRes(pagina === 1 ? { ...r, lista } : { ...r, lista: [...(res?.lista || []), ...lista] })
      setUltima({ texto, m })
    } catch (e) { avisar(e.message, 'error', 9000) } finally { setCargando(false) }
  }
  const buscar = (e) => { e?.preventDefault(); consultar(q, modo === 'titulo_autor' ? 'todo' : modo) }
  const porAutor = (a) => { const n = a.nombre || a; setModo('autor'); setQ(n); consultar(n, 'autor') }
  const alternar = (k) => setTemas((t) => t.includes(k) ? t.filter((x) => x !== k) : [...t, k])

  return (
    <>
      <form onSubmit={buscar} className="col" style={{ marginBottom: 20 }}>
        <BarraModo modo={modo === 'titulo_autor' ? 'todo' : modo} setModo={setModo} />
        <div className="fila">
          <div className="busqueda" style={{ flex: 1 }}>
            {modo === 'autor' ? <User size={17} /> : <Search size={17} />}
            <input autoFocus className="entrada" style={{ fontSize: 16, padding: '12px 12px 12px 36px' }}
              placeholder={modo === 'autor' ? 'Autor (ej. Bruce Alberts)' : modo === 'titulo' ? 'Título del libro' : 'Título, autor, ISBN o editorial'}
              value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <button className="btn primario" style={{ padding: '13px 20px' }} disabled={cargando}>{cargando ? <Loader2 size={16} className="girar" /> : <Search size={16} />}Buscar</button>
        </div>
        <div className="fila">
          <div className="chips">{(esAA ? TIPOS_AA : TEMAS_LG).map(([k, t]) => <button key={k} type="button" className={`chip ${temas.includes(k) ? 'on' : ''}`} onClick={() => alternar(k)}>{t}</button>)}</div>
          <select className="entrada" style={{ width: 120 }} value={ext} onChange={(e) => setExt(e.target.value)}>
            <option value="">Formato</option>{['pdf', 'epub', 'mobi', 'djvu', 'fb2', 'azw3'].map((x) => <option key={x} value={x}>{x.toUpperCase()}</option>)}
          </select>
          <select className="entrada" style={{ width: 150 }} value={idioma} onChange={(e) => setIdioma(e.target.value)} title="Idioma del libro">
            {IDIOMAS_LIB.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
          {esAA ? (
            <select className="entrada" style={{ width: 150 }} value={orden} onChange={(e) => setOrden(e.target.value)}>
              <option value="relevancia">Relevancia</option><option value="recientes">Más recientes</option><option value="antiguos">Más antiguos</option>
              <option value="grandes">Más grandes</option><option value="pequenos">Más pequeños</option>
            </select>
          ) : <input className="entrada mono" style={{ width: 90 }} placeholder="Año" value={anio} onChange={(e) => setAnio(e.target.value.replace(/\D/g, '').slice(0, 4))} />}
        </div>
      </form>

      {!res && <Vacio titulo={esAA ? "Anna's Archive" : 'Library Genesis'}>
        <p style={{ margin: 0, maxWidth: 600 }}>{esAA
          ? "Catálogo unificado de LibGen, Z-Library, Sci-Hub e Internet Archive. Las descargas usan tu clave de miembro si la configuras; si no, se obtienen por md5 desde LibGen. Si tu red bloquea el sitio, activa el túnel Tor."
          : 'Libros, ficción, cómics, revistas y normas mediante libgen-api-enhanced. EPUB, MOBI, FB2 y CBZ se convierten a PDF para leerlos, anotarlos y traducirlos.'}</p>
      </Vacio>}
      {res && <div className="mono" style={{ marginBottom: 12, fontSize: 12 }}>{res.lista.length} RESULTADOS{res.dominio ? ` · ${res.dominio.replace('https://', '')}` : ''}</div>}
      <BarraSeleccion s={seleccion} total={res?.lista.length}>
        <button className="btn chico primario" onClick={descargarSel}><Download size={13} />Descargar {seleccion.n} a la biblioteca</button>
      </BarraSeleccion>
      {res?.lista.map((l) => (
        <div key={l.md5} className={`obra libro ${seleccion.marcado(l) ? 'marcada' : ''}`} style={{ gridTemplateColumns: '22px 64px 1fr' }}>
          <label className="casilla" style={{ alignSelf: 'start', marginTop: 2 }} title="Seleccionar para descargar en lote">
            <input type="checkbox" checked={seleccion.marcado(l)} onChange={() => seleccion.alternar(l)} /></label>
          <img className="tapa" alt="" loading="lazy" onError={(e) => { e.currentTarget.style.visibility = 'hidden' }}
            src={'/api/portada' + qs({ url: l.portada || '', titulo: l.titulo, autor: l.autor })} />
          <div className="col" style={{ gap: 6, minWidth: 0 }}>
            <h3>{l.titulo}</h3>
            <div className="autores"><Autores lista={l.autores?.length ? l.autores : (l.autor ? [l.autor] : [])} onAutor={porAutor} /></div>
            <div className="meta">{[l.editorial, l.anio, l.idioma, l.paginas && `${l.paginas} págs.`].filter(Boolean).join(' · ')}</div>
            <div className="chips">
              {l.extension && <span className={`chip ${['pdf', 'epub', 'mobi', 'fb2', 'cbz'].includes(l.extension) ? 'verde' : ''}`}>{l.extension.toUpperCase()}</span>}
              {l.tamano && <span className="chip">{l.tamano}</span>}
              {l.tipo && <span className="chip">{l.tipo}</span>}
              {l.fuentes && <span className="chip">{l.fuentes}</span>}
              {l.extension && !['pdf', 'epub', 'mobi', 'fb2', 'cbz', 'xps'].includes(l.extension) && <span className="chip acido">Se abre fuera de la app</span>}
            </div>
            <div className="fila">
              <button className="btn chico primario" onClick={() => descargarLibro(l, fuente)}><Download size={13} />Descargar a la biblioteca</button>
              {(l.pagina_url || l.espejos?.[0]) && <button className="btn chico fantasma" onClick={() => abrirUrl(l.pagina_url || l.espejos[0])}><ExternalLink size={13} />Ficha</button>}
            </div>
          </div>
        </div>
      ))}
      {res?.hay_mas && <button className="btn" onClick={() => consultar(ultima.texto, ultima.m, (res.pagina || 1) + 1)} disabled={cargando}><ChevronDown size={15} />Cargar más</button>}
    </>
  )
}

// ---------------------------------------------------------------------------
// Descarga directa (estilo SciHubEVA)
// ---------------------------------------------------------------------------
function Lote({ descargar, ajustes }) {
  const [lote, setLote] = useState('')
  const [fuenteLote, setFuenteLote] = useState(ajustes?.literatura?.fuente || 'auto')
  return (
    <div className="col" style={{ maxWidth: 820 }}>
      <div className="caja">
        <div className="caja-cab"><span className="num">01</span>Consultas · una por línea</div>
        <div className="caja-cuerpo col">
          <textarea className="entrada" rows={10} value={lote} onChange={(e) => setLote(e.target.value)}
            placeholder={'10.1038/s41586-020-2012-7\n32015507\nhttps://doi.org/10.1126/science.abb2507\nhttps://ejemplo.org/articulo.pdf\n10.1371/journal.pone.{0000200-0000210}'} />
          <div className="tenue" style={{ fontSize: 12.5 }}>
            Admite <b>DOI</b>, <b>PMID</b>, <b>URL</b> de artículo o de PDF y texto libre. Los rangos <span className="mono">{'{1-10}'}</span> generan una consulta por número, igual que en SciHubEVA. Máximo 500 por lote.
          </div>
          <div className="fila">
            <Campo etiqueta="Fuente">
              <select className="entrada" value={fuenteLote} onChange={(e) => setFuenteLote(e.target.value)} style={{ width: 280 }}>
                <option value="auto">Automática: acceso abierto y luego Sci-Hub</option>
                <option value="abierto">Solo acceso abierto</option>
                <option value="scihub">Solo Sci-Hub</option>
              </select>
            </Campo>
            <div className="espaciador" />
            <button className="btn primario" style={{ alignSelf: 'end' }} onClick={() => descargar(lote, fuenteLote)} disabled={!lote.trim()}><Download size={15} />Descargar todo</button>
          </div>
        </div>
      </div>
      <div className="aviso-legal">
        <ShieldAlert size={15} style={{ verticalAlign: -2 }} /> Usa Sci-Hub, LibGen y Anna's Archive conforme a la legislación de derechos de autor de tu país. La app prioriza copias de acceso abierto cuando existen. Espejos, túnel Tor, proxy y formato de nombre se configuran en <b>Ajustes → Literatura</b>.
      </div>
    </div>
  )
}

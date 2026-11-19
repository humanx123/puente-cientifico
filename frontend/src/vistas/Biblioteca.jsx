import { useCallback, useEffect, useRef, useState } from 'react'
import {
  FilePlus2, FolderPlus, FolderInput, Star, Clock, Languages, Trash2, Layers, Search, LayoutGrid, List, MoreVertical,
  BookOpen, Pencil, FolderOpen, RotateCcw, X, Sparkles, Folder,
} from 'lucide-react'
import { api, dialogoNativo, qs } from '../api.js'
import { Cabecera, Campo, MenuFlotante, Modal, useAviso, Vacio } from '../ui.jsx'

const VISTAS = [
  { id: 'todos', texto: 'Todos', icono: Layers },
  { id: 'recientes', texto: 'Recientes', icono: Clock },
  { id: 'favoritos', texto: 'Favoritos', icono: Star },
  { id: 'traducidos', texto: 'Traducidos', icono: Languages },
  { id: 'papelera', texto: 'Papelera', icono: Trash2 },
]

export default function Biblioteca({ abrirDoc, version, refrescar, irA }) {
  const avisar = useAviso()
  const [vista, setVista] = useState('todos')
  const [carpeta, setCarpeta] = useState(null)
  const [q, setQ] = useState('')
  const [orden, setOrden] = useState('agregado')
  const [modo, setModo] = useState(() => localStorage.getItem('pc.modo') || 'rejilla')
  const [docs, setDocs] = useState([])
  const [carpetas, setCarpetas] = useState([])
  const [stats, setStats] = useState(null)
  const [global, setGlobal] = useState('')
  const [resGlobal, setResGlobal] = useState(null)
  const [arrastrando, setArrastrando] = useState(false)
  const [menu, setMenu] = useState(null)
  const [editar, setEditar] = useState(null)
  const [importando, setImportando] = useState(false)
  const inputRef = useRef(null)

  const cargar = useCallback(async () => {
    try {
      const [d, c, e] = await Promise.all([
        api.get('/api/documentos' + qs({ vista, carpeta, q, orden })),
        api.get('/api/carpetas'),
        api.get('/api/estado'),
      ])
      setDocs(d); setCarpetas(c); setStats(e.estadisticas)
    } catch (err) { avisar(err.message, 'error') }
  }, [vista, carpeta, q, orden, avisar])

  useEffect(() => { cargar() }, [cargar, version])
  useEffect(() => { localStorage.setItem('pc.modo', modo) }, [modo])
  // Las descargas de OpenAlex completan metadatos unos segundos después de importar
  useEffect(() => { const id = setTimeout(cargar, 4000); return () => clearTimeout(id) }, [version, cargar])

  const resumenImport = (res) => {
    const ok = res.filter((r) => r.ok && !r.documento?.duplicado).length
    const dup = res.filter((r) => r.ok && r.documento?.duplicado).length
    const mal = res.filter((r) => !r.ok)
    avisar(`${ok} importados${dup ? ` · ${dup} ya existían` : ''}${mal.length ? ` · ${mal.length} con error: ${mal[0].error}` : ''}`, mal.length && !ok ? 'error' : 'ok')
    cargar()
    refrescar()
  }

  const subirArchivos = async (files) => {
    const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (!pdfs.length) return avisar('Solo se pueden importar archivos PDF.', 'error')
    const fd = new FormData()
    pdfs.forEach((f) => fd.append('archivos', f))
    setImportando(true)
    try { resumenImport(await api.post('/api/documentos/subir' + (carpeta ? `?carpeta=${carpeta}` : ''), fd)) }
    catch (e) { avisar(e.message, 'error') } finally { setImportando(false) }
  }

  const importar = async (tipo) => {
    const rutas = await dialogoNativo(tipo === 'carpeta' ? 'carpeta' : 'abrir')
    if (rutas === null) return inputRef.current?.click() // navegador: selector HTML
    if (!rutas.length) return
    setImportando(true)
    try { resumenImport(await api.post('/api/documentos/importar-rutas', { rutas, carpeta })) }
    catch (e) { avisar(e.message, 'error') } finally { setImportando(false) }
  }

  const cargarDemo = async () => {
    try { const r = await api.post('/api/documentos/cargar-demo'); avisar(`${r.length} PDF de ejemplo en tu biblioteca.`, 'ok'); cargar(); refrescar() }
    catch (e) { avisar(e.message, 'error') }
  }

  const buscarGlobal = async (e) => {
    e.preventDefault()
    if (!global.trim()) return setResGlobal(null)
    try { setResGlobal(await api.get('/api/buscar' + qs({ q: global }))) } catch (err) { avisar(err.message, 'error') }
  }

  const nuevaCarpeta = async () => {
    const nombre = prompt('Nombre de la carpeta nueva:')
    if (!nombre) return
    try { await api.post('/api/carpetas', { nombre }); cargar() } catch (e) { avisar(e.message, 'error') }
  }

  const accion = async (fn, msg) => { try { await fn(); if (msg) avisar(msg, 'ok'); cargar(); refrescar() } catch (e) { avisar(e.message, 'error') } }

  const abrirMenu = (e, d) => {
    e.preventDefault(); e.stopPropagation()
    const items = vista === 'papelera' ? [
      { texto: 'Restaurar', icono: <RotateCcw size={15} />, accion: () => accion(() => api.post(`/api/documentos/${d.id}/restaurar`), 'Restaurado.') },
      { texto: 'Borrar para siempre', icono: <X size={15} />, peligro: true, accion: () => confirm('¿Borrar definitivamente este documento, sus traducciones y notas?') && accion(() => api.del(`/api/documentos/${d.id}`), 'Borrado.') },
    ] : [
      { texto: 'Abrir', icono: <BookOpen size={15} />, accion: () => abrirDoc(d.id) },
      { texto: d.favorito ? 'Quitar de favoritos' : 'Marcar favorito', icono: <Star size={15} />, accion: () => accion(() => api.patch(`/api/documentos/${d.id}`, { favorito: d.favorito ? 0 : 1 })) },
      { texto: 'Editar datos', icono: <Pencil size={15} />, accion: () => setEditar({ ...d }) },
      '-',
      ...carpetas.map((c) => ({ texto: `Mover a «${c.nombre}»`, icono: <Folder size={15} />, accion: () => accion(() => api.patch(`/api/documentos/${d.id}`, { carpeta_id: c.id }), `Movido a ${c.nombre}.`) })),
      ...(d.carpeta_id ? [{ texto: 'Sacar de la carpeta', icono: <FolderOpen size={15} />, accion: () => accion(() => api.patch(`/api/documentos/${d.id}`, { carpeta_id: null })) }] : []),
      '-',
      { texto: 'Mover a la papelera', icono: <Trash2 size={15} />, peligro: true, accion: () => accion(() => api.post(`/api/documentos/${d.id}/papelera`), 'En la papelera.') },
    ]
    setMenu({ x: e.clientX, y: e.clientY, items })
  }

  const titulo = vista === 'todos' && carpeta ? carpetas.find((c) => c.id === carpeta)?.nombre || 'Carpeta' : VISTAS.find((v) => v.id === vista)?.texto

  return (
    <div className="biblio"
      onDragOver={(e) => { e.preventDefault(); setArrastrando(true) }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setArrastrando(false) }}
      onDrop={(e) => { e.preventDefault(); setArrastrando(false); subirArchivos(e.dataTransfer.files) }}>
      <aside className="filtros">
        <h4>Vistas</h4>
        {VISTAS.map((v) => {
          const I = v.icono
          const n = { todos: stats?.documentos, favoritos: stats?.favoritos, papelera: stats?.papelera }[v.id]
          return (
            <button key={v.id} className={`filtro ${vista === v.id && !carpeta ? 'activo' : ''}`} onClick={() => { setVista(v.id); setCarpeta(null) }}>
              <I size={16} />{v.texto}{n ? <span className="n">{n}</span> : null}
            </button>
          )
        })}
        <h4 style={{ display: 'flex', alignItems: 'center' }}>Carpetas<button className="btn fantasma icono chico" style={{ marginLeft: 'auto' }} onClick={nuevaCarpeta} title="Nueva carpeta"><FolderPlus size={14} /></button></h4>
        {carpetas.length === 0 && <div className="tenue" style={{ padding: '0 16px', fontSize: 12 }}>Sin carpetas todavía.</div>}
        {carpetas.map((c) => (
          <button key={c.id} className={`filtro ${carpeta === c.id ? 'activo' : ''}`} onClick={() => { setVista('todos'); setCarpeta(c.id) }}
            onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, items: [
              { texto: 'Renombrar', icono: <Pencil size={15} />, accion: () => { const n = prompt('Nuevo nombre:', c.nombre); n && accion(() => api.patch(`/api/carpetas/${c.id}`, { nombre: n })) } },
              { texto: 'Eliminar carpeta', icono: <Trash2 size={15} />, peligro: true, accion: () => confirm('Los documentos no se borran, solo salen de la carpeta. ¿Continuar?') && accion(() => api.del(`/api/carpetas/${c.id}`)).then(() => setCarpeta(null)) },
            ] }) }}>
            <Folder size={16} />{c.nombre}<span className="n">{c.n}</span>
          </button>
        ))}
        {vista === 'papelera' && docs.length > 0 && (
          <div style={{ padding: 16 }}><button className="btn peligro chico" onClick={() => confirm('¿Vaciar la papelera definitivamente?') && accion(() => api.post('/api/papelera/vaciar'), 'Papelera vaciada.')}><Trash2 size={14} />Vaciar papelera</button></div>
        )}
      </aside>

      <section style={{ display: 'flex', flexDirection: 'column', minHeight: 0, position: 'relative' }}>
        <Cabecera eti={`// biblioteca · ${docs.length} documentos`} titulo={titulo}>
          <div className="fila">
            <button className="btn primario" onClick={() => importar('abrir')} disabled={importando}><FilePlus2 size={16} />{importando ? 'Importando…' : 'Importar PDF'}</button>
            <button className="btn" onClick={() => importar('carpeta')} disabled={importando}><FolderInput size={16} />Carpeta</button>
            <button className="btn negro" onClick={() => irA('literatura')}><Search size={16} />Buscar literatura</button>
          </div>
          <input ref={inputRef} type="file" accept=".pdf" multiple hidden onChange={(e) => { subirArchivos(e.target.files); e.target.value = '' }} />
        </Cabecera>

        <div className="cuerpo cuerpo-pad">
          {stats && (
            <div className="metricas">
              <div className="metrica"><b>{stats.documentos}</b><span>Documentos</span></div>
              <div className="metrica"><b>{stats.paginas.toLocaleString('es-MX')}</b><span>Páginas</span></div>
              <div className="metrica"><b>{stats.traducciones}</b><span>Traducciones</span></div>
              <div className="metrica"><b>{stats.notas}</b><span>Notas</span></div>
              <div className="metrica"><b>{stats.favoritos}</b><span>Favoritos</span></div>
            </div>
          )}

          <div className="fila" style={{ marginBottom: 18 }}>
            <form onSubmit={buscarGlobal} className="busqueda" style={{ flex: '2 1 320px' }}>
              <Search size={16} />
              <input className="entrada" placeholder="Buscar en el TEXTO de todos los documentos (original y traducción)…" value={global} onChange={(e) => { setGlobal(e.target.value); if (!e.target.value) setResGlobal(null) }} />
            </form>
            <div className="busqueda" style={{ flex: '1 1 200px' }}>
              <Search size={16} />
              <input className="entrada" placeholder="Filtrar por título, autor o DOI" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <select className="entrada" style={{ width: 170 }} value={orden} onChange={(e) => setOrden(e.target.value)}>
              <option value="agregado">Más recientes</option>
              <option value="abierto">Última lectura</option>
              <option value="titulo">Título A–Z</option>
              <option value="anio">Año</option>
              <option value="paginas">Nº de páginas</option>
            </select>
            <div className="grupo-btn">
              <button className={`btn icono ${modo === 'rejilla' ? 'activo' : ''}`} onClick={() => setModo('rejilla')} title="Rejilla"><LayoutGrid size={16} /></button>
              <button className={`btn icono ${modo === 'lista' ? 'activo' : ''}`} onClick={() => setModo('lista')} title="Lista"><List size={16} /></button>
            </div>
          </div>

          {resGlobal && (
            <div className="resultados-globales">
              <div className="fila"><b className="mono">{resGlobal.length} COINCIDENCIAS EN EL TEXTO</b><button className="btn chico fantasma" onClick={() => { setResGlobal(null); setGlobal('') }}><X size={14} />Cerrar</button></div>
              {resGlobal.map((r, i) => (
                <div key={i} className="res-global" onClick={() => abrirDoc(r.documento_id, r.pagina)}>
                  <div className="fila"><b>{r.titulo}</b><span className="chip">P. {r.pagina}</span>{r.tipo === 'traduccion' && <span className="chip senal">Traducción</span>}</div>
                  <div style={{ fontSize: 12.5 }} dangerouslySetInnerHTML={{ __html: escapar(r.fragmento).replace(/\[\[/g, '<mark>').replace(/\]\]/g, '</mark>') }} />
                </div>
              ))}
            </div>
          )}

          {docs.length === 0 ? (
            <Vacio titulo={vista === 'papelera' ? 'Papelera vacía' : 'Tu biblioteca está vacía'}>
              {vista !== 'papelera' && <>
                <p style={{ margin: 0, maxWidth: 520 }}>Arrastra PDF aquí, impórtalos desde una carpeta o búscalos en OpenAlex y Sci-Hub desde <b>Literatura</b>.</p>
                <div className="fila" style={{ justifyContent: 'center' }}>
                  <button className="btn primario" onClick={() => importar('abrir')}><FilePlus2 size={16} />Importar PDF</button>
                  <button className="btn acido" onClick={cargarDemo}><Sparkles size={16} />Cargar ejemplos</button>
                </div>
              </>}
            </Vacio>
          ) : modo === 'rejilla' ? (
            <div className="rejilla">
              {docs.map((d) => (
                <div key={d.id} className="tarjeta" onClick={() => vista !== 'papelera' && abrirDoc(d.id, d.pagina_actual)} onContextMenu={(e) => abrirMenu(e, d)}>
                  <div className="portada">
                    <img loading="lazy" src={`/api/documentos/${d.id}/pagina/1.png?zoom=0.45`} alt="" />
                    <div className="esquina">
                      {d.n_traducciones > 0 && <span className="chip senal">Traducido</span>}
                      {d.origen === 'sci-hub' && <span className="chip negro" style={{ background: 'var(--tinta)', color: 'var(--papel)' }}>Sci-Hub</span>}
                      {d.origen === 'acceso abierto' && <span className="chip verde">OA</span>}
                    </div>
                  </div>
                  <div className="acciones"><button className="btn icono chico" onClick={(e) => abrirMenu(e, d)}><MoreVertical size={14} /></button></div>
                  <div className="info">
                    <h3>{d.titulo}</h3>
                    <div className="meta">{d.autores || 'Autor desconocido'}</div>
                    <div className="meta">{d.anio || '—'} · {d.paginas} PÁG{d.n_notas ? ` · ${d.n_notas} NOTAS` : ''}{d.carpeta ? ` · ${d.carpeta.toUpperCase()}` : ''}</div>
                  </div>
                  {!!d.favorito && <Star className="fav" size={18} fill="var(--senal)" color="var(--tinta)" />}
                </div>
              ))}
            </div>
          ) : (
            <div className="lista-docs">
              <div className="fila-doc cab"><span>Título</span><span>Autores</span><span>Año</span><span>Págs</span><span>Estado</span></div>
              {docs.map((d) => (
                <div key={d.id} className="fila-doc" onClick={() => vista !== 'papelera' && abrirDoc(d.id, d.pagina_actual)} onContextMenu={(e) => abrirMenu(e, d)}>
                  <b style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.favorito ? '★ ' : ''}{d.titulo}</b>
                  <span className="tenue" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.autores || '—'}</span>
                  <span className="mono">{d.anio || '—'}</span>
                  <span className="mono">{d.paginas}</span>
                  <span className="chips">{d.n_traducciones > 0 && <span className="chip senal">TRAD</span>}{d.n_notas > 0 && <span className="chip">{d.n_notas} N</span>}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        {arrastrando && <div className="soltar">Suelta los PDF</div>}
      </section>

      {menu && <MenuFlotante {...menu} onCerrar={() => setMenu(null)} />}
      {editar && (
        <Modal titulo="Editar datos del documento" onCerrar={() => setEditar(null)} pie={<>
          <button className="btn" onClick={() => setEditar(null)}>Cancelar</button>
          <button className="btn primario" onClick={() => accion(() => api.patch(`/api/documentos/${editar.id}`, {
            titulo: editar.titulo, autores: editar.autores, anio: editar.anio ? Number(editar.anio) : null, doi: editar.doi,
          }), 'Datos guardados.').then(() => setEditar(null))}>Guardar</button>
        </>}>
          <Campo etiqueta="Título"><input className="entrada" value={editar.titulo || ''} onChange={(e) => setEditar({ ...editar, titulo: e.target.value })} /></Campo>
          <Campo etiqueta="Autores"><input className="entrada" value={editar.autores || ''} onChange={(e) => setEditar({ ...editar, autores: e.target.value })} /></Campo>
          <div className="form-rejilla">
            <Campo etiqueta="Año"><input className="entrada" value={editar.anio || ''} onChange={(e) => setEditar({ ...editar, anio: e.target.value })} /></Campo>
            <Campo etiqueta="DOI"><input className="entrada" value={editar.doi || ''} onChange={(e) => setEditar({ ...editar, doi: e.target.value })} /></Campo>
          </div>
        </Modal>
      )}
    </div>
  )
}

function escapar(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

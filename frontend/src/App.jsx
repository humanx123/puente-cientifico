import { useCallback, useEffect, useState } from 'react'
import { Library, BookOpen, Search, Newspaper, BookA, Settings, Moon, Sun, PanelLeftClose, PanelLeftOpen, Square, SquareDashed } from 'lucide-react'
import { api } from './api.js'
import { usePeriodico, usePref } from './ui.jsx'
import Biblioteca from './vistas/Biblioteca.jsx'
import Lector from './vistas/Lector.jsx'
import Literatura from './vistas/Literatura.jsx'
import Noticias from './vistas/Noticias.jsx'
import Glosarios from './vistas/Glosarios.jsx'
import Ajustes from './vistas/Ajustes.jsx'

const VISTAS = [
  { id: 'biblioteca', texto: 'Biblioteca', icono: Library },
  { id: 'lector', texto: 'Lector', icono: BookOpen },
  { id: 'literatura', texto: 'Literatura', icono: Search },
  { id: 'noticias', texto: 'Noticias', icono: Newspaper },
  { id: 'glosarios', texto: 'Glosarios', icono: BookA },
  { id: 'ajustes', texto: 'Ajustes', icono: Settings },
]

export default function App() {
  const [vista, setVista] = useState('biblioteca')
  const [doc, setDoc] = useState(null) // { id, pagina }
  const [ajustes, setAjustes] = useState(null)
  const [estado, setEstado] = useState(null)
  const [trabajosT, setTrabajosT] = useState([])
  const [trabajosL, setTrabajosL] = useState([])
  const [noticiasEstado, setNoticiasEstado] = useState(null)
  const [reloj, setReloj] = useState(new Date())
  const [version, setVersion] = useState(0) // fuerza recarga de la biblioteca

  const recargarAjustes = useCallback(() => api.get('/api/ajustes').then(setAjustes).catch(() => {}), [])
  useEffect(() => { recargarAjustes(); api.get('/api/estado').then(setEstado).catch(() => {}) }, [recargarAjustes, version])

  const [plegada, setPlegada] = usePref('nav.plegada', false)
  useEffect(() => {
    const k = (e) => { if (e.ctrlKey && e.key.toLowerCase() === 'b') { e.preventDefault(); setPlegada((p) => !p) } }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [setPlegada])

  const tema = ajustes?.apariencia?.tema || 'claro'
  const skin = ajustes?.apariencia?.skin || 'brutalista'
  useEffect(() => { document.documentElement.dataset.skin = skin }, [skin])
  const cambiarSkin = async () => setAjustes(await api.put('/api/ajustes', { apariencia: { skin: skin === 'minimalista' ? 'brutalista' : 'minimalista' } }))
  useEffect(() => {
    document.documentElement.dataset.tema = tema
    if (ajustes?.apariencia?.acento) document.documentElement.style.setProperty('--senal', ajustes.apariencia.acento)
    document.documentElement.style.zoom = ajustes?.apariencia?.zoom || 1
  }, [tema, ajustes])

  usePeriodico(async () => {
    try {
      const [t, l] = await Promise.all([api.get('/api/trabajos'), api.get('/api/literatura/trabajos')])
      setTrabajosT(t); setTrabajosL(l)
    } catch { /* servidor ocupado */ }
  }, 1500)
  usePeriodico(async () => { try { setNoticiasEstado(await api.get('/api/noticias/estado')) } catch { /* */ } }, 15000)
  useEffect(() => { const id = setInterval(() => setReloj(new Date()), 30000); return () => clearInterval(id) }, [])

  // Cuando termina una descarga, refresca la biblioteca
  const descargasOk = trabajosL.filter((t) => t.estado === 'ok').length
  useEffect(() => { if (descargasOk) setVersion((v) => v + 1) }, [descargasOk])

  const abrirDoc = (id, pagina = null) => { setDoc({ id, pagina, t: Date.now() }); setVista('lector') }
  const cambiarTema = async () => {
    const nuevo = tema === 'oscuro' ? 'claro' : 'oscuro'
    setAjustes(await api.put('/api/ajustes', { apariencia: { tema: nuevo } }))
  }

  const tActivos = trabajosT.filter((t) => ['preparando', 'en_curso'].includes(t.estado))
  const lActivos = trabajosL.filter((t) => ['en_cola', 'buscando', 'descargando', 'captcha'].includes(t.estado))
  const captchas = trabajosL.filter((t) => t.estado === 'captcha').length

  return (
    <div className={`app ${plegada ? 'nav-plegada' : ''}`}>
      <nav className="nav">
        <div className="marca">
          <div className="marca-logo">
            <div className="marca-cuadro">P</div>
            <h1>Puente<br />Científico</h1>
            {!plegada && <button className="btn-plegar" title="Ocultar menú (Ctrl+B)" onClick={() => setPlegada(true)}><PanelLeftClose size={17} /></button>}
          </div>
          {plegada && <button className="btn-plegar" style={{ margin: '10px auto 0', display: 'block' }} title="Mostrar menú (Ctrl+B)" onClick={() => setPlegada(false)}><PanelLeftOpen size={17} /></button>}
          <small>LEER · TRADUCIR · ENCONTRAR</small>
        </div>
        <div className="nav-lista">
          {VISTAS.map((v, i) => {
            const I = v.icono
            const extra = v.id === 'literatura' && lActivos.length ? <span className={`chip ${captchas ? 'acido' : 'senal'} contador`}>{captchas ? 'CAPTCHA' : lActivos.length}</span>
              : v.id === 'lector' && tActivos.length ? <span className="chip senal contador">{tActivos.length}</span> : null
            return (
              <button key={v.id} className={`nav-item ${vista === v.id ? 'activo' : ''}`} onClick={() => setVista(v.id)} title={v.texto}>
                <span className="num">{String(i + 1).padStart(2, '0')}</span>
                <I size={17} strokeWidth={skin === 'minimalista' ? 1.9 : 2.4} />
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="txt">{v.texto}</span>{extra}</span>
              </button>
            )
          })}
        </div>
        <div className="nav-pie">
          <button className="btn chico" onClick={cambiarSkin} title="Cambiar entre skin brutalista y minimalista">
            {skin === 'minimalista' ? <Square size={14} /> : <SquareDashed size={14} />}<span className="solo-ancho">{skin === 'minimalista' ? 'Brutalista' : 'Minimalista'}</span></button>
          <button className="btn chico" onClick={cambiarTema} title="Tema claro u oscuro">{tema === 'oscuro' ? <Sun size={14} /> : <Moon size={14} />}<span className="solo-ancho">{tema === 'oscuro' ? 'Modo claro' : 'Modo oscuro'}</span></button>
          <span className="tenue solo-ancho">v{estado?.version || '—'} · {estado?.estadisticas?.documentos ?? 0} DOCS</span>
        </div>
      </nav>

      <main className="principal">
        {vista === 'biblioteca' && <Biblioteca abrirDoc={abrirDoc} version={version} refrescar={() => setVersion((v) => v + 1)} irA={setVista} />}
        {vista === 'lector' && <Lector doc={doc} abrirDoc={abrirDoc} irA={setVista} ajustes={ajustes} trabajos={trabajosT} refrescar={() => setVersion((v) => v + 1)} />}
        {vista === 'literatura' && <Literatura trabajos={trabajosL} abrirDoc={abrirDoc} ajustes={ajustes} />}
        {vista === 'noticias' && <Noticias estado={noticiasEstado} />}
        {vista === 'glosarios' && <Glosarios />}
        {vista === 'ajustes' && <Ajustes ajustes={ajustes} setAjustes={setAjustes} estado={estado} />}
      </main>

      <footer className="estado-barra">
        <span><span className={`punto ${tActivos.length || lActivos.length ? 'ocupado' : ''}`} />{tActivos.length || lActivos.length ? 'TRABAJANDO' : 'LISTO'}</span>
        {tActivos.map((t) => (
          <span key={t.id}>TRADUCIENDO «{t.titulo.slice(0, 32)}» {t.paginas_hechas}/{t.paginas.length} PÁG · {t.segmentos_hechos}/{t.segmentos_total || '…'} SEG</span>
        ))}
        {lActivos.length > 0 && <span>DESCARGAS: {lActivos.length} EN CURSO{captchas ? ` · ${captchas} CAPTCHA PENDIENTE` : ''} <button onClick={() => setVista('literatura')}>VER</button></span>}
        <span style={{ marginLeft: 'auto' }}>
          NOTICIAS: {noticiasEstado?.en_curso ? 'ACTUALIZANDO…' : noticiasEstado?.ultima ? `ACT. ${new Date(noticiasEstado.ultima).toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })}` : '—'}
        </span>
        <span>{reloj.toLocaleDateString('es-MX', { weekday: 'short', day: '2-digit', month: 'short' }).toUpperCase()} {reloj.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })}</span>
      </footer>
    </div>
  )
}

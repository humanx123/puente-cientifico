import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { X, AlertTriangle, Check, Info } from 'lucide-react'

// ---------- Avisos (toasts) ----------
const AvisoCtx = createContext(() => {})
export const useAviso = () => useContext(AvisoCtx)

export function ProveedorAvisos({ children }) {
  const [avisos, setAvisos] = useState([])
  const avisar = useCallback((texto, tipo = 'info', ms = 4200) => {
    const id = Math.random().toString(36).slice(2)
    setAvisos((a) => [...a.slice(-3), { id, texto: String(texto), tipo }])
    setTimeout(() => setAvisos((a) => a.filter((x) => x.id !== id)), ms)
  }, [])
  return (
    <AvisoCtx.Provider value={avisar}>
      {children}
      <div className="avisos">
        {avisos.map((a) => (
          <div key={a.id} className={`aviso ${a.tipo}`}>
            {a.tipo === 'error' ? <AlertTriangle size={18} /> : a.tipo === 'ok' ? <Check size={18} /> : <Info size={18} />}
            <div style={{ flex: 1 }}>{a.texto}</div>
            <button className="btn fantasma icono chico" onClick={() => setAvisos((x) => x.filter((y) => y.id !== a.id))}><X size={14} /></button>
          </div>
        ))}
      </div>
    </AvisoCtx.Provider>
  )
}

// ---------- Modal ----------
export function Modal({ titulo, onCerrar, children, pie, ancho }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onCerrar?.()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onCerrar])
  return (
    <div className="velo" onMouseDown={(e) => e.target === e.currentTarget && onCerrar?.()}>
      <div className={`modal ${ancho ? 'ancho' : ''}`}>
        <div className="modal-cab"><h3>{titulo}</h3><button onClick={onCerrar}><X size={20} /></button></div>
        <div className="modal-cuerpo">{children}</div>
        {pie && <div className="modal-pie">{pie}</div>}
      </div>
    </div>
  )
}

// ---------- Menú flotante ----------
export function MenuFlotante({ x, y, items, onCerrar }) {
  const ref = useRef(null)
  useEffect(() => {
    const c = (e) => ref.current && !ref.current.contains(e.target) && onCerrar()
    setTimeout(() => window.addEventListener('mousedown', c), 0)
    return () => window.removeEventListener('mousedown', c)
  }, [onCerrar])
  const left = Math.min(x, window.innerWidth - 230)
  const top = Math.min(y, window.innerHeight - items.length * 40 - 20)
  return (
    <div className="menu-flot" ref={ref} style={{ left, top }}>
      {items.map((it, i) => it === '-' ? <hr key={i} /> : (
        <button key={i} onClick={() => { onCerrar(); it.accion() }} style={it.peligro ? { color: 'var(--rojo)' } : null}>
          {it.icono}{it.texto}
        </button>
      ))}
    </div>
  )
}

export function Campo({ etiqueta, ayuda, children, ancho }) {
  return (
    <label className={`campo ${ancho ? 'ancho' : ''}`}>
      <span>{etiqueta}</span>
      {children}
      {ayuda && <small>{ayuda}</small>}
    </label>
  )
}

export function Casilla({ checked, onChange, children }) {
  return (
    <label className="casilla">
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  )
}

export function Cabecera({ eti, titulo, mediano, children }) {
  return (
    <div className="cabecera">
      <div className="titulo-vista">
        <div className="eti">{eti}</div>
        <h2 className={mediano ? 'mediano' : ''} title={typeof titulo === 'string' ? titulo : undefined}>{titulo}</h2>
      </div>
      {children}
    </div>
  )
}

export function Vacio({ titulo, children }) {
  return <div className="vacio"><h3>{titulo}</h3>{children}</div>
}

export function usePeriodico(fn, ms, deps = []) {
  useEffect(() => {
    let vivo = true
    const tick = async () => { if (vivo) await fn() }
    tick()
    const id = setInterval(tick, ms)
    return () => { vivo = false; clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

// ---------- Preferencias de diseño guardadas en este equipo ----------
export function usePref(clave, inicial) {
  const [v, setV] = useState(() => {
    try { const x = localStorage.getItem('pc.' + clave); return x === null ? inicial : JSON.parse(x) } catch { return inicial }
  })
  useEffect(() => { try { localStorage.setItem('pc.' + clave, JSON.stringify(v)) } catch { /* sin almacenamiento */ } }, [clave, v])
  return [v, setV]
}

// ---------- Panel lateral redimensionable y plegable ----------
// Arrastra el borde para cambiar el ancho; doble clic (o el botón) lo oculta/muestra.
export function PanelLateral({ clave, ancho = 260, min = 160, max = 640, lado = 'izq', className = '', titulo = '', children }) {
  const [w, setW] = usePref(`panel.${clave}`, ancho)
  const [oculto, setOculto] = usePref(`panel.${clave}.oculto`, false)
  const arrastre = useRef(null)
  const empezar = (e) => {
    e.preventDefault()
    arrastre.current = { x: e.clientX, w }
    document.body.classList.add('redimensionando')
    const mover = (ev) => {
      const d = ev.clientX - arrastre.current.x
      setW(Math.max(min, Math.min(max, arrastre.current.w + (lado === 'izq' ? d : -d))))
    }
    const soltar = () => {
      document.body.classList.remove('redimensionando')
      window.removeEventListener('mousemove', mover)
      window.removeEventListener('mouseup', soltar)
    }
    window.addEventListener('mousemove', mover)
    window.addEventListener('mouseup', soltar)
  }
  if (oculto) {
    return (
      <button className={`panel-pestana ${lado}`} title={`Mostrar ${titulo || 'panel'}`} onClick={() => setOculto(false)}>
        <span>{titulo || '•••'}</span>
      </button>
    )
  }
  return (
    <aside className={`panel-lateral ${lado} ${className}`} style={{ width: w }}>
      {children}
      <div className={`divisor ${lado}`} onMouseDown={empezar} onDoubleClick={() => setOculto(true)}
        title="Arrastra para cambiar el ancho · doble clic para ocultar" />
    </aside>
  )
}

export function Progreso({ valor }) {
  return <div className="progreso"><div style={{ width: `${Math.max(0, Math.min(100, valor))}%` }} /></div>
}

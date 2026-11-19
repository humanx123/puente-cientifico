import { useEffect, useRef, useState } from 'react'
import { Send, X, Save, FileText, Loader2 } from 'lucide-react'
import { api } from '../api.js'
import { useAviso } from '../ui.jsx'

function ConCitas({ texto, irAPagina }) {
  const partes = texto.split(/(\[p(?:ág)?\.?\s*\d+\])/gi)
  return partes.map((p, i) => {
    const m = p.match(/\[p(?:ág)?\.?\s*(\d+)\]/i)
    return m ? <span key={i} className="cita" onClick={() => irAPagina(Number(m[1]))}>{p}</span> : <span key={i}>{p}</span>
  })
}

export default function Asistente({ docId, pagina, irAPagina, seleccion, limpiarSeleccion, onNota, onCerrar }) {
  const avisar = useAviso()
  const [ambito, setAmbito] = useState('documento')
  const [msgs, setMsgs] = useState([])
  const [texto, setTexto] = useState('')
  const [pensando, setPensando] = useState(false)
  const finRef = useRef(null)

  useEffect(() => { if (seleccion) setAmbito('seleccion') }, [seleccion])
  useEffect(() => { setMsgs([]) }, [docId])
  useEffect(() => { finRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, pensando])

  const enviar = async (pregunta, ambitoForzado) => {
    const q = (pregunta ?? texto).trim()
    if (!q || pensando) return
    const amb = ambitoForzado || ambito
    const historial = msgs.map(({ role, content }) => ({ role, content }))
    setMsgs((m) => [...m, { role: 'user', content: q, ambito: amb }])
    setTexto('')
    setPensando(true)
    try {
      const r = await api.post('/api/asistente', {
        doc_id: docId, pregunta: q, ambito: amb, pagina: amb === 'seleccion' ? seleccion?.pagina : pagina,
        seleccion: amb === 'seleccion' ? seleccion?.texto : '', historial,
      })
      setMsgs((m) => [...m, { role: 'assistant', content: r.respuesta, citas: r.citas, paginas: r.paginas_consultadas, modelo: r.modelo, pregunta: q }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', content: '⚠ ' + e.message, error: true }])
    } finally { setPensando(false) }
  }

  const guardarNota = async (m) => {
    try {
      const n = await api.post(`/api/documentos/${docId}/notas`, { pagina: m.citas?.[0] || pagina, tipo: 'asistente', texto: `P: ${m.pregunta}\n\nR: ${m.content}` })
      onNota(n); avisar('Respuesta guardada como nota.', 'ok')
    } catch (e) { avisar(e.message, 'error') }
  }

  return (
    <aside className="asistente">
      <div className="caja-cab" style={{ background: 'var(--tinta)', color: 'var(--papel)' }}>
        <span className="num">AI</span>Asistente del documento
        <button className="btn fantasma icono chico" style={{ marginLeft: 'auto', color: 'inherit' }} onClick={onCerrar}><X size={15} /></button>
      </div>
      <div className="chat">
        {msgs.length === 0 && (
          <div className="col" style={{ fontSize: 13 }}>
            <p style={{ margin: 0 }} className="tenue">Pregunta sobre el documento, la página actual o un fragmento seleccionado. Las respuestas citan páginas comprobables.</p>
            <button className="btn chico" onClick={() => enviar('Haz un resumen estructurado del documento: objetivo, métodos, resultados principales y conclusiones, con citas de página.', 'documento')}><FileText size={13} />Resumir el documento</button>
            <button className="btn chico" onClick={() => enviar('¿Cuáles son las limitaciones del estudio?', 'documento')}>¿Limitaciones del estudio?</button>
            <button className="btn chico" onClick={() => enviar('Explica esta página en lenguaje sencillo.', 'pagina')}>Explicar la página actual</button>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`} style={m.error ? { background: 'var(--rojo)', color: '#fff' } : null}>
            {m.role === 'assistant' ? <ConCitas texto={m.content} irAPagina={irAPagina} /> : m.content}
            {m.role === 'assistant' && !m.error && (
              <div className="msg-pie">
                <span className="mono tenue" style={{ fontSize: 10 }}>{m.modelo} · consultó p. {m.paginas?.join(', ') || '—'}</span>
                <button className="btn chico" onClick={() => guardarNota(m)}><Save size={12} />Guardar nota</button>
              </div>
            )}
          </div>
        ))}
        {pensando && <div className="msg assistant"><Loader2 size={14} className="girar" /> Pensando…</div>}
        <div ref={finRef} />
      </div>
      <div className="chat-entrada">
        {seleccion && ambito === 'seleccion' && (
          <div className="chip acido" style={{ whiteSpace: 'normal', textTransform: 'none', display: 'flex' }}>
            <span style={{ flex: 1 }}>Selección p. {seleccion.pagina}: «{seleccion.texto.slice(0, 120)}…»</span>
            <button className="btn fantasma icono chico" onClick={() => { limpiarSeleccion(); setAmbito('documento') }}><X size={12} /></button>
          </div>
        )}
        <div className="grupo-btn" style={{ width: '100%' }}>
          {[['documento', 'Documento'], ['pagina', `Pág. ${pagina}`], ['seleccion', 'Selección'], ['libre', 'Libre']].map(([k, t]) => (
            <button key={k} className={`btn chico ${ambito === k ? 'activo' : ''}`} style={{ flex: 1 }} disabled={k === 'seleccion' && !seleccion} onClick={() => setAmbito(k)}>{t}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <textarea className="entrada" rows={2} style={{ fontFamily: 'var(--sans)', fontSize: 13 }} placeholder="Escribe tu pregunta… (Enter para enviar)"
            value={texto} onChange={(e) => setTexto(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar() } }} />
          <button className="btn primario" onClick={() => enviar()} disabled={pensando}><Send size={16} /></button>
        </div>
      </div>
    </aside>
  )
}

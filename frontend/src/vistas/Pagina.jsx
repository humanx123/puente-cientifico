import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// Agrupa palabras de PyMuPDF (x0,y0,x1,y1,texto,bloque,línea) en líneas para una selección natural
function agruparLineas(palabras) {
  const lineas = new Map()
  for (const [x0, y0, x1, y1, t, b, l] of palabras) {
    const k = `${b}-${l}`
    const ln = lineas.get(k)
    if (!ln) lineas.set(k, { x0, y0, x1, y1, t })
    else { ln.x1 = Math.max(ln.x1, x1); ln.y0 = Math.min(ln.y0, y0); ln.y1 = Math.max(ln.y1, y1); ln.t += ' ' + t }
  }
  return [...lineas.values()]
}

function CapaTexto({ docId, n, variante, ancho, alto }) {
  const [lineas, setLineas] = useState(null)
  const ref = useRef(null)
  useEffect(() => {
    let vivo = true
    api.get(`/api/documentos/${docId}/texto/${n}?variante=${variante}`).then((r) => vivo && setLineas(agruparLineas(r.palabras))).catch(() => {})
    return () => { vivo = false }
  }, [docId, n, variante])
  // Ajusta cada línea al ancho real de la palabra en la imagen
  useLayoutEffect(() => {
    if (!ref.current) return
    for (const s of ref.current.children) {
      const objetivo = parseFloat(s.dataset.w)
      s.style.transform = ''
      const real = s.getBoundingClientRect().width / (window.devicePixelRatio ? 1 : 1)
      if (real > 0) s.style.transform = `scaleX(${objetivo / real})`
    }
  }, [lineas, ancho])
  if (!lineas) return null
  return (
    <div className="capa-texto" ref={ref}>
      {lineas.map((l, i) => {
        const h = (l.y1 - l.y0) * alto
        return (
          <span key={i} data-w={(l.x1 - l.x0) * ancho}
            style={{ left: l.x0 * ancho, top: l.y0 * alto, fontSize: h * 0.92, height: h, fontFamily: 'Arial, sans-serif' }}>
            {l.t + ' '}
          </span>
        )
      })}
    </div>
  )
}

function Pagina({ docId, n, ancho, alto, zoom, variante, sello, visible, resaltes = [], busqueda = [], segmentos = null, onSegmento, etiqueta }) {
  const [cargada, setCargada] = useState(false)
  const escala = Math.min(3, zoom * (window.devicePixelRatio || 1))
  const src = `/api/documentos/${docId}/pagina/${n}.png?zoom=${escala.toFixed(2)}&variante=${variante}${sello ? `&v=${sello}` : ''}`
  useEffect(() => { setCargada(false) }, [src])
  return (
    <div className="pagina" style={{ width: ancho, height: alto }} data-pag={n} data-variante={variante}>
      <span className="etiqueta-pag">{etiqueta || `P. ${n}`}</span>
      {visible ? (
        <>
          <img src={src} alt="" onLoad={() => setCargada(true)} draggable={false} />
          {!cargada && <div className="cargando-pag">RENDERIZANDO P. {n}…</div>}
          <div className="capa-resaltes">
            {resaltes.flatMap((h) => h.rects.map((r, i) => (
              <div key={`${h.id}-${i}`} style={{
                left: r[0] * ancho, top: h.tipo === 'subrayado' ? r[3] * alto - 2 : r[1] * alto, width: (r[2] - r[0]) * ancho,
                height: h.tipo === 'subrayado' ? 3 : (r[3] - r[1]) * alto, background: h.color, opacity: h.tipo === 'subrayado' ? 1 : 0.55,
              }} />
            )))}
          </div>
          <div className="capa-resaltes capa-busqueda">
            {busqueda.map((r, i) => <div key={i} style={{ left: r[0] * ancho - 1, top: r[1] * alto - 1, width: (r[2] - r[0]) * ancho + 2, height: (r[3] - r[1]) * alto + 2 }} />)}
          </div>
          {segmentos ? (
            <div className="capa-segmentos">
              {segmentos.filter((s) => s.estado !== 'omitido').map((s) => (
                <div key={s.id} className={s.estado} title={s.estado === 'error' ? `Error: ${s.error || ''} — clic para reintentar` : 'Clic para ver o editar la traducción'}
                  style={{ left: s.rect[0] * ancho, top: s.rect[1] * alto, width: (s.rect[2] - s.rect[0]) * ancho, height: (s.rect[3] - s.rect[1]) * alto }}
                  onClick={() => onSegmento?.(s)} />
              ))}
            </div>
          ) : (
            <CapaTexto docId={docId} n={n} variante={variante} ancho={ancho} alto={alto} />
          )}
        </>
      ) : <div className="cargando-pag">P. {n}</div>}
    </div>
  )
}

export default memo(Pagina)

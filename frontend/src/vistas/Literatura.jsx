import { useState } from 'react'
import { Search, Download, ExternalLink, BookOpen, Unlock, Quote, Trash2, Zap, Loader2, ShieldAlert, ChevronDown } from 'lucide-react'
import { api, abrirUrl, qs } from '../api.js'
import { Cabecera, Campo, Casilla, Modal, useAviso, Vacio } from '../ui.jsx'

const ESTADOS = {
  en_cola: ['EN COLA', ''], buscando: ['BUSCANDO', 'acido'], descargando: ['DESCARGANDO', 'acido'], captcha: ['CAPTCHA', 'senal'],
  ok: ['EN BIBLIOTECA', 'verde'], duplicado: ['YA EXISTÍA', 'azul'], error: ['ERROR', 'rojo'],
}

export default function Literatura({ trabajos, abrirDoc, ajustes }) {
  const avisar = useAviso()
  const [pestana, setPestana] = useState('buscar')
  const [q, setQ] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [orden, setOrden] = useState('relevancia')
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [lote, setLote] = useState('')
  const [fuenteLote, setFuenteLote] = useState(ajustes?.literatura?.fuente || 'auto')
  const [captcha, setCaptcha] = useState('')
  const [abiertos, setAbiertos] = useState({})

  const buscar = async (pagina = 1, e) => {
    e?.preventDefault()
    if (!q.trim()) return
    setCargando(true)
    try {
      const r = await api.get('/api/literatura/buscar' + qs({ q, pagina, abierto, desde, hasta, orden }))
      setRes(pagina === 1 ? r : { ...r, obras: [...(res?.obras || []), ...r.obras] })
    } catch (err) { avisar(err.message, 'error') } finally { setCargando(false) }
  }

  const descargar = async (consultas, fuente, obra) => {
    try {
      const r = await api.post('/api/literatura/descargar', { consultas, fuente, obra })
      avisar(`${r.length} ${r.length === 1 ? 'descarga añadida' : 'descargas añadidas'} a la cola.`, 'ok')
    } catch (e) { avisar(e.message, 'error') }
  }

  const pendienteCaptcha = trabajos.find((t) => t.estado === 'captcha')
  const enviarCaptcha = async (respuesta) => {
    try { await api.post(`/api/literatura/trabajos/${pendienteCaptcha.id}/captcha`, { respuesta }); setCaptcha('') }
    catch (e) { avisar(e.message, 'error') }
  }

  return (
    <>
      <Cabecera eti="// literatura · openalex + acceso abierto + sci-hub" titulo="Literatura">
        <div className="grupo-btn">
          <button className={`btn ${pestana === 'buscar' ? 'activo' : ''}`} onClick={() => setPestana('buscar')}><Search size={15} />Buscar</button>
          <button className={`btn ${pestana === 'lote' ? 'activo' : ''}`} onClick={() => setPestana('lote')}><Zap size={15} />Descarga directa</button>
        </div>
      </Cabecera>
      <div className="lit" style={{ flex: 1, minHeight: 0 }}>
        <div className="lit-res">
          {pestana === 'buscar' ? (
            <>
              <form onSubmit={(e) => buscar(1, e)} className="col" style={{ marginBottom: 20 }}>
                <div className="fila">
                  <div className="busqueda" style={{ flex: 1 }}>
                    <Search size={17} />
                    <input autoFocus className="entrada" style={{ fontSize: 16, padding: '12px 12px 12px 36px' }} placeholder="Título, palabras clave o DOI (ej. measles vaccine Mexico 2025)"
                      value={q} onChange={(e) => setQ(e.target.value)} />
                  </div>
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
              {!res && <Vacio titulo="Busca en 250 millones de obras">
                <p style={{ margin: 0, maxWidth: 560 }}>Metadatos de <b>OpenAlex</b>. El PDF se obtiene de una copia de acceso abierto o, si lo eliges, de <b>Sci-Hub</b> con rotación de espejos y CAPTCHA asistido. Todo se importa a tu biblioteca sin duplicados.</p>
              </Vacio>}
              {res && <div className="mono" style={{ marginBottom: 12, fontSize: 12 }}>{res.total.toLocaleString('es-MX')} RESULTADOS</div>}
              {res?.obras.map((o) => (
                <div key={o.id} className="obra">
                  <h3>{o.titulo}</h3>
                  <div className="autores">{o.autores.join(', ') || 'Autoría no disponible'}</div>
                  <div className="meta">{[o.anio, o.revista, o.doi && `DOI ${o.doi}`].filter(Boolean).join(' · ')}</div>
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
              {res?.hay_mas && <button className="btn" onClick={() => buscar(res.pagina + 1)} disabled={cargando}><ChevronDown size={15} />Cargar más</button>}
            </>
          ) : (
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
                <ShieldAlert size={15} style={{ verticalAlign: -2 }} /> Usa Sci-Hub de acuerdo con la legislación de derechos de autor de tu país. La app prioriza copias de acceso abierto cuando existen. Los espejos, XPath, proxy y formato de nombre se configuran en <b>Ajustes → Literatura</b>.
              </div>
            </div>
          )}
        </div>

        <aside className="cola">
          <div className="caja-cab" style={{ background: 'var(--tinta)', color: 'var(--papel)' }}>
            <span className="num">{trabajos.length}</span>Cola de descargas
            <button className="btn chico" style={{ marginLeft: 'auto' }} onClick={() => api.post('/api/literatura/limpiar')}><Trash2 size={12} />Limpiar</button>
          </div>
          <div style={{ overflow: 'auto', flex: 1 }}>
            {trabajos.length === 0 && <div className="tenue" style={{ padding: 16, fontSize: 13 }}>Las descargas aparecerán aquí con su registro en tiempo real.</div>}
            {trabajos.map((t) => {
              const [txt, cls] = ESTADOS[t.estado] || [t.estado, '']
              const ab = abiertos[t.id] ?? ['captcha', 'error', 'buscando', 'descargando'].includes(t.estado)
              return (
                <div key={t.id} className="trabajo">
                  <div className="fila" style={{ cursor: 'pointer' }} onClick={() => setAbiertos((a) => ({ ...a, [t.id]: !ab }))}>
                    <span className={`chip ${cls}`}>{['buscando', 'descargando'].includes(t.estado) && <Loader2 size={11} className="girar" />}{txt}</span>
                    <span className="mono" style={{ fontSize: 10.5 }}>{t.tipo.toUpperCase()}</span>
                  </div>
                  <b style={{ fontSize: 12.5, wordBreak: 'break-word' }}>{t.obra?.titulo || t.consulta}</b>
                  {ab && (
                    <div className="consola">
                      {t.registro.map((l, i) => <div key={i} className={l.nivel}>[{l.t}] {l.msg}</div>)}
                    </div>
                  )}
                  <div className="fila">
                    {t.documento_id && <button className="btn chico primario" onClick={() => abrirDoc(t.documento_id)}><BookOpen size={12} />Abrir</button>}
                    {t.estado === 'error' && t.pagina_url && <button className="btn chico" onClick={() => abrirUrl(t.pagina_url)}><ExternalLink size={12} />Abrir página</button>}
                    {t.estado === 'error' && <button className="btn chico" onClick={() => descargar(t.consulta, t.fuente === 'scihub' ? 'auto' : 'scihub', t.obra)}>Reintentar</button>}
                  </div>
                </div>
              )
            })}
          </div>
        </aside>
      </div>

      {pendienteCaptcha && (
        <Modal titulo="Verificación CAPTCHA" onCerrar={() => enviarCaptcha(null)} pie={<>
          <button className="btn" onClick={() => enviarCaptcha(null)}>Cancelar descarga</button>
          <button className="btn primario" onClick={() => enviarCaptcha(captcha)} disabled={!captcha.trim()}>Enviar</button>
        </>}>
          <p style={{ margin: 0 }}>Sci-Hub pide verificación para <b>{pendienteCaptcha.obra?.titulo || pendienteCaptcha.consulta}</b>. Escribe el código de la imagen.</p>
          {pendienteCaptcha.captcha?.imagen && <img src={pendienteCaptcha.captcha.imagen} alt="CAPTCHA" style={{ border: '3px solid var(--tinta)', background: '#fff', maxWidth: '100%', imageRendering: 'pixelated', minHeight: 60 }} />}
          <input autoFocus className="entrada mono" style={{ fontSize: 20, letterSpacing: '0.2em' }} value={captcha} onChange={(e) => setCaptcha(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && captcha.trim() && enviarCaptcha(captcha)} />
          {pendienteCaptcha.captcha?.pagina && <button className="btn chico fantasma" onClick={() => abrirUrl(pendienteCaptcha.captcha.pagina)}><ExternalLink size={12} />Abrir la página en el navegador</button>}
        </Modal>
      )}
    </>
  )
}

import { useEffect, useState } from 'react'
import { Plus, Copy, Trash2, Save, Upload, Download, Wand2, BookA, Loader2 } from 'lucide-react'
import { api, IDIOMAS_UI } from '../api.js'
import { Cabecera, Campo, Modal, useAviso, Vacio } from '../ui.jsx'

export default function Glosarios() {
  const avisar = useAviso()
  const [lista, setLista] = useState([])
  const [actual, setActual] = useState(null)
  const [filtro, setFiltro] = useState('')
  const [importar, setImportar] = useState(false)
  const [extraer, setExtraer] = useState(false)
  const [sucio, setSucio] = useState(false)

  const cargar = async (selId) => {
    const g = await api.get('/api/glosarios')
    setLista(g)
    const elegido = g.find((x) => x.id === (selId ?? actual?.id)) || g[0]
    if (elegido) { setActual(structuredClone(elegido)); setSucio(false) }
  }
  useEffect(() => { cargar() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const elegir = (g) => {
    if (sucio && !confirm('Hay cambios sin guardar. ¿Descartarlos?')) return
    setActual(structuredClone(g)); setSucio(false)
  }
  const cambiar = (c) => { setActual((a) => ({ ...a, ...c })); setSucio(true) }
  const cambiarTermino = (i, j, v) => { const t = actual.terminos.map((x) => [...x]); t[i][j] = v; cambiar({ terminos: t }) }

  const guardar = async () => {
    try { const g = await api.put(`/api/glosarios/${actual.id}`, actual); avisar('Glosario guardado.', 'ok'); cargar(g.id) } catch (e) { avisar(e.message, 'error') }
  }
  const nuevo = async () => { const g = await api.post('/api/glosarios', { nombre: 'Nuevo glosario', origen: 'en', destino: 'es', terminos: [] }); cargar(g.id) }
  const duplicar = async () => { const g = await api.post(`/api/glosarios/${actual.id}/duplicar`); avisar('Copia creada.', 'ok'); cargar(g.id) }
  const borrar = async () => { if (!confirm(`¿Eliminar «${actual.nombre}»?`)) return; await api.del(`/api/glosarios/${actual.id}`); setActual(null); cargar(-1) }

  const terminos = actual?.terminos || []
  const visibles = terminos.map((t, i) => [t, i]).filter(([t]) => !filtro || (t[0] + ' ' + t[1]).toLowerCase().includes(filtro.toLowerCase()))

  return (
    <>
      <Cabecera eti="// glosarios · terminología obligatoria para la traducción" titulo="Glosarios">
        <div className="fila">
          <button className="btn" onClick={() => setExtraer(true)}><Wand2 size={15} />Extraer de un documento</button>
          <button className="btn primario" onClick={nuevo}><Plus size={15} />Nuevo glosario</button>
        </div>
      </Cabecera>
      <div className="glos" style={{ flex: 1, minHeight: 0 }}>
        <aside className="filtros">
          <h4>{lista.length} glosarios</h4>
          {lista.map((g) => (
            <button key={g.id} className={`filtro ${actual?.id === g.id ? 'activo' : ''}`} onClick={() => elegir(g)}>
              <BookA size={15} /><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.nombre}</span>
              <span className="n">{g.origen}→{g.destino} · {g.n}</span>
            </button>
          ))}
        </aside>
        <div className="cuerpo cuerpo-pad">
          {!actual ? <Vacio titulo="Sin glosarios"><button className="btn primario" onClick={nuevo}><Plus size={15} />Crear uno</button></Vacio> : (
            <div className="col">
              <div className="form-rejilla" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                <Campo etiqueta="Nombre"><input className="entrada" value={actual.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} /></Campo>
                <Campo etiqueta="Idioma original"><select className="entrada" value={actual.origen} onChange={(e) => cambiar({ origen: e.target.value })}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Campo>
                <Campo etiqueta="Idioma destino"><select className="entrada" value={actual.destino} onChange={(e) => cambiar({ destino: e.target.value })}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Campo>
              </div>
              <div className="fila">
                <button className="btn primario" onClick={guardar} disabled={!sucio}><Save size={14} />{sucio ? 'Guardar cambios' : 'Guardado'}</button>
                <button className="btn" onClick={() => cambiar({ terminos: [['', ''], ...terminos] })}><Plus size={14} />Término</button>
                <button className="btn" onClick={() => setImportar(true)}><Upload size={14} />Importar TXT/CSV</button>
                <a className="btn" href={`/api/glosarios/${actual.id}/csv`} download><Download size={14} />Exportar CSV</a>
                <button className="btn" onClick={duplicar}><Copy size={14} />Duplicar</button>
                <div className="espaciador" />
                {actual.integrado ? <span className="chip acido">Integrado</span> : null}
                <button className="btn peligro" onClick={borrar}><Trash2 size={14} />Eliminar</button>
              </div>
              <input className="entrada" placeholder={`Filtrar entre ${terminos.length} términos`} value={filtro} onChange={(e) => setFiltro(e.target.value)} />
              <table className="tabla">
                <thead><tr><th style={{ width: 48 }}>#</th><th>{IDIOMAS_UI[actual.origen]}</th><th>{IDIOMAS_UI[actual.destino]}</th><th style={{ width: 50 }}></th></tr></thead>
                <tbody>
                  {visibles.map(([t, i]) => (
                    <tr key={i}>
                      <td className="mono tenue" style={{ padding: '0 10px', fontSize: 11 }}>{i + 1}</td>
                      <td><input value={t[0]} onChange={(e) => cambiarTermino(i, 0, e.target.value)} /></td>
                      <td><input value={t[1]} onChange={(e) => cambiarTermino(i, 1, e.target.value)} /></td>
                      <td><button className="btn fantasma icono chico" onClick={() => cambiar({ terminos: terminos.filter((_, j) => j !== i) })}><Trash2 size={13} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      {importar && <ModalImportar onCerrar={() => setImportar(false)} onTerminos={(t) => { cambiar({ terminos: [...terminos, ...t] }); setImportar(false); avisar(`${t.length} términos añadidos. Recuerda guardar.`, 'ok') }} />}
      {extraer && <ModalExtraer glosario={actual} onCerrar={() => setExtraer(false)} onTerminos={(t) => { cambiar({ terminos: [...terminos, ...t] }); setExtraer(false); avisar(`${t.length} términos añadidos. Recuerda guardar.`, 'ok') }} />}
    </>
  )
}

function ModalImportar({ onCerrar, onTerminos }) {
  const avisar = useAviso()
  const [texto, setTexto] = useState('')
  const analizar = async () => {
    try { const t = await api.post('/api/glosarios/analizar', { contenido: texto }); if (!t.length) return avisar('No se encontraron pares de términos.', 'error'); onTerminos(t) }
    catch (e) { avisar(e.message, 'error') }
  }
  return (
    <Modal titulo="Importar términos" onCerrar={onCerrar} pie={<><button className="btn" onClick={onCerrar}>Cancelar</button><button className="btn primario" onClick={analizar}>Importar</button></>}>
      <p style={{ margin: 0 }} className="tenue">Pega un CSV <span className="mono">origen,destino</span> o un TXT con una línea por término separada por tabulador, <span className="mono">=</span>, <span className="mono">-&gt;</span> o <span className="mono">;</span>.</p>
      <input type="file" accept=".csv,.txt,.tsv" onChange={async (e) => { const f = e.target.files[0]; if (f) setTexto(await f.text()) }} />
      <textarea className="entrada" rows={12} value={texto} onChange={(e) => setTexto(e.target.value)} placeholder={'viral load = carga viral\nhost cell\tcélula hospedera'} />
    </Modal>
  )
}

function ModalExtraer({ glosario, onCerrar, onTerminos }) {
  const [docs, setDocs] = useState([])
  const [doc, setDoc] = useState('')
  const [cands, setCands] = useState(null)
  const [trad, setTrad] = useState({})
  const [cargando, setCargando] = useState(false)
  useEffect(() => { api.get('/api/documentos').then((d) => { setDocs(d); if (d[0]) setDoc(String(d[0].id)) }) }, [])
  const extraer = async () => { setCargando(true); try { setCands(await api.get(`/api/documentos/${doc}/sugerir-terminos`)) } finally { setCargando(false) } }
  const elegidos = Object.entries(trad).filter(([, v]) => v.trim())
  return (
    <Modal titulo="Extraer términos candidatos" onCerrar={onCerrar} ancho pie={<>
      <button className="btn" onClick={onCerrar}>Cancelar</button>
      <button className="btn primario" disabled={!elegidos.length} onClick={() => onTerminos(elegidos.map(([k, v]) => [k, v]))}>Añadir {elegidos.length} a «{glosario?.nombre}»</button>
    </>}>
      <div className="fila">
        <select className="entrada" style={{ flex: 1 }} value={doc} onChange={(e) => setDoc(e.target.value)}>{docs.map((d) => <option key={d.id} value={d.id}>{d.titulo}</option>)}</select>
        <button className="btn negro" onClick={extraer} disabled={!doc || cargando}>{cargando ? <Loader2 size={14} className="girar" /> : <Wand2 size={14} />}Extraer</button>
      </div>
      {cands && (
        <table className="tabla">
          <thead><tr><th>Término frecuente</th><th style={{ width: 70 }}>Veces</th><th>Tu traducción (déjala vacía para omitir)</th></tr></thead>
          <tbody>{cands.map((c) => (
            <tr key={c.termino}>
              <td style={{ padding: '6px 10px' }}><b>{c.termino}</b></td>
              <td className="mono" style={{ padding: '6px 10px' }}>{c.frecuencia}</td>
              <td><input value={trad[c.termino] || ''} onChange={(e) => setTrad({ ...trad, [c.termino]: e.target.value })} /></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </Modal>
  )
}

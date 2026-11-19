import { useEffect, useState } from 'react'
import { Save, RefreshCw, FlaskConical, FolderOpen, Loader2, Cpu, BookMarked, Newspaper, Palette, Info, Trash2, Plus } from 'lucide-react'
import { api, abrirRuta, abrirUrl, dialogoNativo, IDIOMAS_UI } from '../api.js'
import { Cabecera, Campo, Casilla, PanelLateral, useAviso, usePeriodico } from '../ui.jsx'

const PRESETS = [
  { n: 'OpenAI', url: 'https://api.openai.com/v1', m: 'gpt-4o-mini' },
  { n: 'Groq', url: 'https://api.groq.com/openai/v1', m: 'llama-3.3-70b-versatile' },
  { n: 'OpenRouter', url: 'https://openrouter.ai/api/v1', m: 'meta-llama/llama-3.3-70b-instruct:free' },
  { n: 'DeepSeek', url: 'https://api.deepseek.com/v1', m: 'deepseek-chat' },
  { n: 'NVIDIA NIM', url: 'https://integrate.api.nvidia.com/v1', m: 'meta/llama-3.3-70b-instruct' },
  { n: 'Google Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai', m: 'gemini-2.0-flash' },
  { n: 'LM Studio (local)', url: 'http://127.0.0.1:1234/v1', m: '' },
]

const SECCIONES = [
  { id: 'ia', texto: 'Traducción e IA', icono: Cpu },
  { id: 'literatura', texto: 'Literatura y Sci-Hub', icono: BookMarked },
  { id: 'noticias', texto: 'Noticias', icono: Newspaper },
  { id: 'apariencia', texto: 'Apariencia', icono: Palette },
  { id: 'acerca', texto: 'Acerca de', icono: Info },
]

export default function Ajustes({ ajustes, setAjustes, estado }) {
  const avisar = useAviso()
  const [sec, setSec] = useState('ia')
  const [a, setA] = useState(null)
  const [modelos, setModelos] = useState([])
  const [cargandoM, setCargandoM] = useState(false)
  const [probando, setProbando] = useState(false)
  useEffect(() => { if (ajustes) setA(structuredClone(ajustes)) }, [ajustes])
  if (!a) return null

  const set = (s, k, v) => setA((x) => ({ ...x, [s]: { ...x[s], [k]: v } }))
  const guardar = async () => {
    try { setAjustes(await api.put('/api/ajustes', a)); avisar('Ajustes guardados.', 'ok') } catch (e) { avisar(e.message, 'error') }
  }
  const cargarModelos = async () => {
    setCargandoM(true)
    try { await api.put('/api/ajustes', { traduccion: a.traduccion }); const m = await api.get('/api/modelos'); setModelos(m); if (!m.length) avisar('El proveedor no devolvió modelos.', 'info') }
    catch (e) { avisar(e.message, 'error') } finally { setCargandoM(false) }
  }
  const probar = async () => {
    setProbando(true)
    try { setAjustes(await api.put('/api/ajustes', a)); const r = await api.post('/api/probar-modelo'); avisar(`✔ ${r.modelo}: «${r.muestra}»`, 'ok', 8000) }
    catch (e) { avisar(e.message, 'error', 8000) } finally { setProbando(false) }
  }
  const t = a.traduccion
  const l = a.literatura

  return (
    <>
      <Cabecera eti="// ajustes · se guardan en tu perfil de windows" titulo="Ajustes">
        <button className="btn primario" onClick={guardar}><Save size={15} />Guardar ajustes</button>
      </Cabecera>
      <div className="ajustes" style={{ flex: 1, minHeight: 0 }}>
        <PanelLateral clave="ajustes" ancho={220} min={150} max={520} titulo="Secciones"><div className="filtros">
          {SECCIONES.map((s) => { const I = s.icono; return <button key={s.id} className={`filtro ${sec === s.id ? 'activo' : ''}`} onClick={() => setSec(s.id)}><I size={16} />{s.texto}</button> })}
        </div></PanelLateral>
        <div className="cuerpo cuerpo-pad" style={{ maxWidth: 980 }}>
          {sec === 'ia' && (
            <div className="col">
              <div className="grupo-btn" style={{ width: 'fit-content' }}>
                <button className={`btn ${t.proveedor === 'freellmapi' ? 'activo' : ''}`} onClick={() => set('traduccion', 'proveedor', 'freellmapi')}>FreeLLMAPI (recomendado)</button>
                <button className={`btn ${t.proveedor === 'openai' ? 'activo' : ''}`} onClick={() => set('traduccion', 'proveedor', 'openai')}>API compatible con OpenAI</button>
                <button className={`btn ${t.proveedor === 'ollama' ? 'activo' : ''}`} onClick={() => set('traduccion', 'proveedor', 'ollama')}>Ollama (local)</button>
              </div>
              {t.proveedor === 'freellmapi' ? (
                <PanelFreeLLMAPI t={t} set={set} setAjustes={setAjustes} cargarModelos={cargarModelos} cargandoM={cargandoM} />
              ) : t.proveedor === 'ollama' ? (
                <div className="form-rejilla">
                  <Campo etiqueta="Dirección de Ollama"><input className="entrada mono" value={t.ollama_url} onChange={(e) => set('traduccion', 'ollama_url', e.target.value)} /></Campo>
                  <Campo etiqueta="Modelo" ayuda="Recomendado: qwen2.5:7b o superior. En equipos modestos, qwen2.5:3b.">
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input className="entrada mono" list="modelos" value={t.ollama_modelo} onChange={(e) => set('traduccion', 'ollama_modelo', e.target.value)} placeholder="qwen2.5:7b" />
                      <button className="btn" onClick={cargarModelos} title="Obtener modelos instalados">{cargandoM ? <Loader2 size={15} className="girar" /> : <RefreshCw size={15} />}</button>
                    </div>
                  </Campo>
                  <div className="ancho tenue" style={{ fontSize: 12.5 }}>¿No tienes Ollama? Descárgalo en <a href="#" onClick={(e) => { e.preventDefault(); abrirUrl('https://ollama.com/download') }}>ollama.com</a> y ejecuta <span className="mono">ollama pull qwen2.5:7b</span>.</div>
                </div>
              ) : (
                <div className="form-rejilla">
                  <Campo etiqueta="Proveedor (preajuste)" ancho>
                    <div className="chips">{PRESETS.map((p) => <button key={p.n} className={`chip ${t.openai_url === p.url ? 'on' : ''}`} onClick={() => setA((x) => ({ ...x, traduccion: { ...x.traduccion, openai_url: p.url, openai_modelo: p.m || x.traduccion.openai_modelo } }))}>{p.n}</button>)}</div>
                  </Campo>
                  <Campo etiqueta="URL base"><input className="entrada mono" value={t.openai_url} onChange={(e) => set('traduccion', 'openai_url', e.target.value)} /></Campo>
                  <Campo etiqueta="Clave de API" ayuda={t.openai_clave_configurada ? 'Hay una clave guardada. Escribe otra para reemplazarla.' : 'Se guarda solo en este equipo.'}>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input className="entrada mono" type="password" value={t.openai_clave} placeholder={t.openai_clave_configurada ? '•••••••• guardada' : 'sk-…'} onChange={(e) => set('traduccion', 'openai_clave', e.target.value)} />
                      {t.openai_clave_configurada && <button className="btn" title="Borrar clave" onClick={async () => { setAjustes(await api.put('/api/ajustes', { borrar_clave: 'traduccion.openai_clave' })); avisar('Clave borrada.', 'ok') }}><Trash2 size={15} /></button>}
                    </div>
                  </Campo>
                  <Campo etiqueta="Modelo">
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input className="entrada mono" list="modelos" value={t.openai_modelo} onChange={(e) => set('traduccion', 'openai_modelo', e.target.value)} />
                      <button className="btn" onClick={cargarModelos}>{cargandoM ? <Loader2 size={15} className="girar" /> : <RefreshCw size={15} />}</button>
                    </div>
                  </Campo>
                </div>
              )}
              <datalist id="modelos">{modelos.map((m) => <option key={m} value={m} />)}</datalist>
              {modelos.length > 0 && <div className="chips">{modelos.slice(0, 60).map((m) => <button key={m} className="chip" onClick={() => set('traduccion', { ollama: 'ollama_modelo', freellmapi: 'freellmapi_modelo' }[t.proveedor] || 'openai_modelo', m)}>{m}</button>)}</div>}
              <div className="form-rejilla">
                <Campo etiqueta="Idioma original por defecto"><select className="entrada" value={t.idioma_origen} onChange={(e) => set('traduccion', 'idioma_origen', e.target.value)}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Campo>
                <Campo etiqueta="Traducir a"><select className="entrada" value={t.idioma_destino} onChange={(e) => set('traduccion', 'idioma_destino', e.target.value)}>{Object.entries(IDIOMAS_UI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Campo>
                <Campo etiqueta={`Temperatura · ${t.temperatura}`} ayuda="Más baja = traducción más literal y estable."><input type="range" min="0" max="1" step="0.05" value={t.temperatura} onChange={(e) => set('traduccion', 'temperatura', Number(e.target.value))} /></Campo>
                <Campo etiqueta="Red para el proveedor de IA">
                  <select className="entrada" value={t.proxy_modo} onChange={(e) => set('traduccion', 'proxy_modo', e.target.value)}>
                    <option value="sistema">Proxy del sistema</option><option value="directo">Conexión directa</option><option value="manual">Proxy HTTP manual</option>
                  </select>
                </Campo>
                {t.proxy_modo === 'manual' && <Campo etiqueta="Proxy HTTP" ancho><input className="entrada mono" placeholder="http://127.0.0.1:7890" value={t.proxy_url} onChange={(e) => set('traduccion', 'proxy_url', e.target.value)} /></Campo>}
                <Campo etiqueta="Modelo del asistente" ayuda="Vacío = el mismo que la traducción." ancho>
                  <input className="entrada mono" list="modelos" value={a.asistente.modelo} onChange={(e) => set('asistente', 'modelo', e.target.value)} placeholder="(igual que traducción)" />
                </Campo>
              </div>
              <div><button className="btn negro" onClick={probar} disabled={probando}>{probando ? <Loader2 size={15} className="girar" /> : <FlaskConical size={15} />}Probar traducción</button></div>
            </div>
          )}

          {sec === 'literatura' && (
            <div className="col">
              <PanelOpenAlex l={l} set={set} guardar={async () => setAjustes(await api.put('/api/ajustes', { literatura: l }))} />
              <PanelTunel l={l} set={set} />
              <div className="caja">
                <div className="caja-cab"><span className="num">LB</span>LibGen y Anna's Archive</div>
                <div className="caja-cuerpo form-rejilla">
                  <Campo etiqueta="Espejo de LibGen" ayuda="Dominio de libgen-api-enhanced: li, bz, la, vg, gl…">
                    <input className="entrada mono" value={l.libgen_espejo} onChange={(e) => set('literatura', 'libgen_espejo', e.target.value.replace(/^\./, ''))} />
                  </Campo>
                  <Campo etiqueta="Clave de miembro de Anna's Archive (opcional)" ayuda="Activa la descarga rápida oficial. Sin clave se descarga por md5 desde LibGen.">
                    <input className="entrada mono" type="password" placeholder={l.annas_clave_configurada ? '•••• guardada' : ''} value={l.annas_clave} onChange={(e) => set('literatura', 'annas_clave', e.target.value)} />
                  </Campo>
                  <Campo etiqueta="Dominios de Anna's Archive (se prueban en orden)" ancho ayuda="Cambian con frecuencia: consulta la sección FAQ de un espejo que funcione. Admite direcciones .onion si usas Tor.">
                    <ListaEditable valores={l.annas_dominios} onChange={(v) => set('literatura', 'annas_dominios', v)} placeholder="annas-archive.xx" />
                  </Campo>
                  <div className="ancho"><Casilla checked={l.annas_doh} onChange={(v) => set('literatura', 'annas_doh', v)}>Resolver con DNS sobre HTTPS (Cloudflare) si el DNS de mi proveedor no encuentra el dominio</Casilla></div>
                </div>
              </div>
              <div className="form-rejilla">
                <Campo etiqueta="Fuente de PDF por defecto">
                  <select className="entrada" value={l.fuente} onChange={(e) => set('literatura', 'fuente', e.target.value)}>
                    <option value="auto">Automática (acceso abierto → Sci-Hub)</option><option value="abierto">Solo acceso abierto</option><option value="scihub">Solo Sci-Hub</option>
                  </select>
                </Campo>
                <Campo etiqueta="Espejo principal de Sci-Hub"><input className="entrada mono" value={l.scihub_url} onChange={(e) => set('literatura', 'scihub_url', e.target.value)} /></Campo>
                <Campo etiqueta="Espejos alternativos (se prueban en orden)" ancho>
                  <ListaEditable valores={l.scihub_espejos} onChange={(v) => set('literatura', 'scihub_espejos', v)} placeholder="https://sci-hub.xx" />
                </Campo>
                <Campo etiqueta="XPath del PDF (SciHubEVA)" ancho ayuda="Se prueban en orden sobre la página del artículo.">
                  <ListaEditable valores={l.xpaths_pdf} onChange={(v) => set('literatura', 'xpaths_pdf', v)} placeholder='//embed[@id="pdf"]' />
                </Campo>
                <Campo etiqueta="XPath del id del CAPTCHA"><ListaEditable valores={l.xpath_captcha_id} onChange={(v) => set('literatura', 'xpath_captcha_id', v)} /></Campo>
                <Campo etiqueta="XPath de la imagen del CAPTCHA"><ListaEditable valores={l.xpath_captcha_img} onChange={(v) => set('literatura', 'xpath_captcha_img', v)} /></Campo>
                <Campo etiqueta="Formato del nombre de archivo" ayuda="Variables: {id} {year} {author} {title}">
                  <input className="entrada mono" value={l.formato_nombre} onChange={(e) => set('literatura', 'formato_nombre', e.target.value)} />
                </Campo>
                <Campo etiqueta="Guardar también una copia en" ayuda="Opcional. Además de la biblioteca.">
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className="entrada mono" value={l.guardar_copia_en} onChange={(e) => set('literatura', 'guardar_copia_en', e.target.value)} placeholder="(no guardar copia)" />
                    <button className="btn" onClick={async () => { const r = await dialogoNativo('carpeta'); if (r?.length) set('literatura', 'guardar_copia_en', r[0]) }}><FolderOpen size={15} /></button>
                  </div>
                </Campo>
                <Campo etiqueta="Tiempo de espera (ms)"><input className="entrada mono" type="number" value={l.tiempo_espera_ms} onChange={(e) => set('literatura', 'tiempo_espera_ms', Number(e.target.value))} /></Campo>
                <Campo etiqueta="Reintentos de red"><input className="entrada mono" type="number" min="0" max="10" value={l.reintentos} onChange={(e) => set('literatura', 'reintentos', Number(e.target.value))} /></Campo>
                <Campo etiqueta="Agente de usuario (User-Agent)" ancho><input className="entrada mono" value={l.agente_usuario} onChange={(e) => set('literatura', 'agente_usuario', e.target.value)} /></Campo>
                <div className="ancho"><Casilla checked={l.verificacion_auto !== false} onChange={(v) => set('literatura', 'verificacion_auto', v)}>Si una revista o espejo bloquea programas (403 / «Just a moment»), abrir la ventana de verificación integrada y capturar el PDF automáticamente</Casilla></div>
                <div className="ancho"><Casilla checked={l.sobrescribir} onChange={(v) => set('literatura', 'sobrescribir', v)}>Sobrescribir archivos con el mismo nombre en la carpeta de copia</Casilla></div>
              </div>
              <div className="aviso-legal">Usa Sci-Hub conforme a la legislación de tu país. Si un espejo responde con DDoS-Guard, cambia de espejo, de red o usa un proxy.</div>
            </div>
          )}

          {sec === 'noticias' && (
            <div className="form-rejilla">
              <Campo etiqueta="Actualizar cada (horas)"><input className="entrada mono" type="number" min="0.5" step="0.5" value={a.noticias.intervalo_horas} onChange={(e) => set('noticias', 'intervalo_horas', Number(e.target.value))} /></Campo>
              <Campo etiqueta="Máximo de elementos guardados" ayuda="Las noticias guardadas nunca se borran."><input className="entrada mono" type="number" min="50" value={a.noticias.max_elementos} onChange={(e) => set('noticias', 'max_elementos', Number(e.target.value))} /></Campo>
            </div>
          )}

          {sec === 'apariencia' && (
            <div className="form-rejilla">
              <Campo etiqueta="Skin" ayuda="Brutalista: bordes gruesos y sombras duras. Minimalista: limpio, bordes finos y esquinas suaves.">
                <div className="grupo-btn"><button className={`btn ${a.apariencia.skin !== 'minimalista' ? 'activo' : ''}`} onClick={() => set('apariencia', 'skin', 'brutalista')}>Brutalista</button><button className={`btn ${a.apariencia.skin === 'minimalista' ? 'activo' : ''}`} onClick={() => set('apariencia', 'skin', 'minimalista')}>Minimalista</button></div>
              </Campo>
              <Campo etiqueta="Diseño de paneles" ayuda="Arrastra el borde de cualquier panel para cambiar su ancho; doble clic para ocultarlo. Ctrl+B oculta el menú.">
                <button className="btn" onClick={() => { Object.keys(localStorage).filter((k) => k.startsWith('pc.panel.') || k === 'pc.nav.plegada').forEach((k) => localStorage.removeItem(k)); location.reload() }}>Restablecer paneles</button>
              </Campo>
              <Campo etiqueta="Tema">
                <div className="grupo-btn"><button className={`btn ${a.apariencia.tema === 'claro' ? 'activo' : ''}`} onClick={() => set('apariencia', 'tema', 'claro')}>Claro</button><button className={`btn ${a.apariencia.tema === 'oscuro' ? 'activo' : ''}`} onClick={() => set('apariencia', 'tema', 'oscuro')}>Oscuro</button></div>
              </Campo>
              <Campo etiqueta="Color de señal">
                <div className="chips">{['#ff3d00', '#2b4bff', '#00a86b', '#e00034', '#9b5cff', '#0a0a0a'].map((c) => <button key={c} className="chip" onClick={() => set('apariencia', 'acento', c)} style={{ background: c, width: 34, height: 26, outline: a.apariencia.acento === c ? '3px solid var(--tinta)' : 'none', outlineOffset: 2 }} />)}</div>
              </Campo>
              <Campo etiqueta={`Escala de la interfaz · ${Math.round(a.apariencia.zoom * 100)}%`}><input type="range" min="0.8" max="1.3" step="0.05" value={a.apariencia.zoom} onChange={(e) => set('apariencia', 'zoom', Number(e.target.value))} /></Campo>
            </div>
          )}

          {sec === 'acerca' && (
            <div className="col">
              <div className="caja">
                <div className="caja-cab"><span className="num">PC</span>Puente Científico v{estado?.version}</div>
                <div className="caja-cuerpo col">
                  <p style={{ margin: 0 }}>App de escritorio para Windows que reúne en español tres proyectos de código abierto:</p>
                  <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
                    <li><b>PageBridge</b> (txp666): biblioteca PDF, traducción con maquetación, vista comparada, glosarios, asistente y búsqueda de literatura.</li>
                    <li><b>SciHubEVA</b> (leovan): cliente de Sci-Hub con espejos, XPath, CAPTCHA, rangos, proxy y nombres de archivo.</li>
                    <li><b>science-hub</b> (goldruma): agregador de avisos y noticias con etiquetas por nivel, área y categoría.</li>
                    <li><b>libgen-api-enhanced</b> (onurhanak): búsqueda en Library Genesis por título y autor, temas, filtros y enlaces directos.</li>
                    <li><b>Anna's Archive</b> (LilyLoops/annas-archive): búsqueda en su catálogo unificado y descarga rápida de miembros.</li>
                    <li><b>Tor</b> (The Tor Project): túnel de privacidad para literatura, con puentes Snowflake y obfs4.</li>
                  </ul>
                  <div className="fila">
                    <button className="btn chico" onClick={() => abrirUrl('https://github.com/txp666/PageBridge')}>PageBridge</button>
                    <button className="btn chico" onClick={() => abrirUrl('https://github.com/leovan/SciHubEVA')}>SciHubEVA</button>
                    <button className="btn chico" onClick={() => abrirUrl('https://github.com/goldruma/science-hub')}>science-hub</button>
                  </div>
                </div>
              </div>
              <div className="caja">
                <div className="caja-cab"><span className="num">//</span>Tus datos</div>
                <div className="caja-cuerpo col">
                  <div className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>{estado?.datos}</div>
                  <div className="fila">
                    <button className="btn chico" onClick={() => abrirRuta(estado.datos)}><FolderOpen size={13} />Abrir carpeta de datos</button>
                    <button className="btn chico" onClick={() => abrirRuta(estado.exportaciones)}><FolderOpen size={13} />Abrir exportaciones</button>
                  </div>
                  <div className="tenue" style={{ fontSize: 12.5 }}>Biblioteca, traducciones, notas y ajustes viven en tu perfil de Windows. Desinstalar la app no los borra.</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function PanelFreeLLMAPI({ t, set, setAjustes, cargarModelos, cargandoM }) {
  const avisar = useAviso()
  const [est, setEst] = useState(null)
  const [ocupado, setOcupado] = useState(null)
  const refrescar = () => api.get('/api/freellmapi/estado').then(setEst).catch(() => setEst(null))
  useEffect(() => { refrescar() }, [t.freellmapi_url, t.freellmapi_clave_configurada])
  const accion = async (k, fn, ok) => {
    setOcupado(k)
    try { const r = await fn(); if (r?.corriendo !== undefined) setEst(r); setAjustes(await api.get('/api/ajustes')); avisar(ok, 'ok') }
    catch (e) { avisar(e.message, 'error', 7000) } finally { setOcupado(null) }
  }
  const luz = (b) => <span className={`chip ${b ? 'verde' : 'rojo'}`}>{b ? 'SÍ' : 'NO'}</span>
  return (
    <div className="col">
      <div className="aviso-legal" style={{ background: 'var(--papel-2)', color: 'var(--tinta)' }}>
        <b>FreeLLMAPI</b> une las capas gratuitas de Gemini, Groq, Cerebras, SambaNova, NVIDIA, Mistral, OpenRouter, GitHub Models y más tras un solo endpoint.
        Con el modelo <span className="mono">auto</span> elige el mejor disponible y cambia solo si uno llega a su límite. Las claves de los proveedores se gestionan en su panel.
      </div>
      <div className="caja">
        <div className="caja-cab"><span className="num">FL</span>Estado
          <button className="btn chico" style={{ marginLeft: 'auto' }} onClick={refrescar}><RefreshCw size={12} />Comprobar</button></div>
        <div className="caja-cuerpo">
          <div className="fila" style={{ gap: 18 }}>
            <span className="fila" style={{ gap: 6 }}>Instalado en este equipo {luz(est?.instalado)}</span>
            <span className="fila" style={{ gap: 6 }}>Servidor activo {luz(est?.corriendo)}</span>
            <span className="fila" style={{ gap: 6 }}>Clave válida {luz(est?.clave_valida)}</span>
          </div>
          {est?.carpeta && <div className="mono tenue" style={{ fontSize: 11, marginTop: 8 }}>{est.carpeta}</div>}
          <div className="fila" style={{ marginTop: 12 }}>
            <button className="btn primario chico" disabled={!!ocupado} onClick={() => accion('imp', () => api.post('/api/freellmapi/importar-clave', { ruta: t.freellmapi_ruta }), 'Clave unificada importada desde FreeLLMAPI.')}>
              {ocupado === 'imp' ? <Loader2 size={13} className="girar" /> : <Save size={13} />}Importar clave del equipo</button>
            {!est?.corriendo && <button className="btn chico negro" disabled={!!ocupado} onClick={() => accion('arr', () => api.post('/api/freellmapi/arrancar'), 'FreeLLMAPI iniciado.')}>
              {ocupado === 'arr' ? <Loader2 size={13} className="girar" /> : <FlaskConical size={13} />}Iniciar FreeLLMAPI</button>}
            {est?.panel && <button className="btn chico" onClick={() => abrirUrl(est.panel)}>Abrir panel (claves y cadena)</button>}
          </div>
        </div>
      </div>
      <div className="form-rejilla">
        <Campo etiqueta="Dirección del endpoint" ayuda="Local por defecto. También sirve una instancia remota (Raspberry Pi, servidor).">
          <input className="entrada mono" value={t.freellmapi_url} onChange={(e) => set('traduccion', 'freellmapi_url', e.target.value)} />
        </Campo>
        <Campo etiqueta="Clave unificada" ayuda={t.freellmapi_clave_configurada ? 'Hay una clave guardada en este equipo.' : 'Se importa sola o pégala desde el panel Keys.'}>
          <input className="entrada mono" type="password" placeholder={t.freellmapi_clave_configurada ? '•••••••• guardada' : 'freellmapi-…'} value={t.freellmapi_clave} onChange={(e) => set('traduccion', 'freellmapi_clave', e.target.value)} />
        </Campo>
        <Campo etiqueta="Modelo" ayuda="auto = el router elige y conmuta ante límites. Para traducir más rápido, sube Groq o Cerebras al principio de la Fallback Chain en el panel, o fija un modelo rápido.">
          <div style={{ display: 'flex', gap: 8 }}>
            <input className="entrada mono" list="modelos" value={t.freellmapi_modelo} onChange={(e) => set('traduccion', 'freellmapi_modelo', e.target.value)} />
            <button className="btn" onClick={cargarModelos} title="Ver modelos disponibles">{cargandoM ? <Loader2 size={15} className="girar" /> : <RefreshCw size={15} />}</button>
          </div>
        </Campo>
        <Campo etiqueta="Carpeta de FreeLLMAPI" ayuda="Vacío = detectar (por ejemplo %USERPROFILE%\freellmapi).">
          <div style={{ display: 'flex', gap: 8 }}>
            <input className="entrada mono" value={t.freellmapi_ruta} placeholder="(detectar)" onChange={(e) => set('traduccion', 'freellmapi_ruta', e.target.value)} />
            <button className="btn" onClick={async () => { const r = await dialogoNativo('carpeta'); if (r?.length) set('traduccion', 'freellmapi_ruta', r[0]) }}><FolderOpen size={15} /></button>
          </div>
        </Campo>
        <div className="ancho"><Casilla checked={t.freellmapi_autoarranque} onChange={(v) => set('traduccion', 'freellmapi_autoarranque', v)}>Iniciar FreeLLMAPI automáticamente cuando haga falta traducir o preguntar</Casilla></div>
      </div>
    </div>
  )
}

function PanelOpenAlex({ l, set, guardar }) {
  const avisar = useAviso()
  const [prueba, setPrueba] = useState(null)
  const [probando, setProbando] = useState(false)
  const probar = async () => {
    setProbando(true)
    try {
      await guardar()
      const r = await api.post('/api/literatura/probar-openalex')
      setPrueba(r)
      avisar(r.ok ? `OpenAlex responde: ${r.restantes} de ${r.limite} créditos disponibles hoy.` : `OpenAlex respondió HTTP ${r.codigo}.`, r.ok ? 'ok' : 'error', 8000)
    } catch (e) { avisar(e.message, 'error', 9000) } finally { setProbando(false) }
  }
  const horas = prueba?.reinicio_s ? Math.round(prueba.reinicio_s / 360) / 10 : null
  return (
    <div className="caja">
      <div className="caja-cab"><span className="num">OA</span>Búsqueda de artículos · OpenAlex</div>
      <div className="caja-cuerpo col">
        <div className="tenue" style={{ fontSize: 12.5 }}>
          OpenAlex funciona con créditos diarios. Sin clave hay 1000 al día: una búsqueda por texto gasta 10, ver las obras de un autor gasta 1 y consultar un DOI es gratis.
          La app espacia las peticiones, guarda en caché las búsquedas 30 minutos y, si se agota el cupo, cambia sola a <b>Crossref</b> (gratuito y sin cupo diario).
        </div>
        <div className="form-rejilla">
          <Campo etiqueta="Fuente de metadatos">
            <select className="entrada" value={l.metadatos || 'auto'} onChange={(e) => set('literatura', 'metadatos', e.target.value)}>
              <option value="auto">Automática: OpenAlex y, si se agota, Crossref</option>
              <option value="openalex">Solo OpenAlex</option>
              <option value="crossref">Solo Crossref (sin cupo, sin acceso abierto detallado)</option>
            </select>
          </Campo>
          <Campo etiqueta="Correo de contacto (recomendado)" ayuda="OpenAlex y Crossref dan mejor servicio a quien se identifica. Solo se envía a ellos.">
            <input className="entrada" type="email" placeholder="tu@correo.com" value={l.openalex_correo} onChange={(e) => set('literatura', 'openalex_correo', e.target.value)} />
          </Campo>
          <Campo etiqueta="Clave de API de OpenAlex (gratuita)" ancho
            ayuda="1) Pulsa «Obtener clave», entra con Google o tu correo. 2) Copia la clave de la página de API. 3) Pégala aquí y pulsa «Guardar y probar».">
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="entrada mono" type="password" placeholder={l.openalex_clave_configurada ? '•••••••• guardada' : 'pega aquí tu clave'} value={l.openalex_clave} onChange={(e) => set('literatura', 'openalex_clave', e.target.value)} />
              <button className="btn" onClick={() => abrirUrl('https://openalex.org/settings/api')}>Obtener clave</button>
              <button className="btn primario" onClick={probar} disabled={probando}>{probando ? <Loader2 size={14} className="girar" /> : <FlaskConical size={14} />}Guardar y probar</button>
            </div>
          </Campo>
        </div>
        {prueba && (
          <div className="chips">
            <span className={`chip ${prueba.ok ? 'verde' : 'rojo'}`}>{prueba.ok ? 'Conexión correcta' : `Error ${prueba.codigo}`}</span>
            <span className="chip">{prueba.con_clave ? 'Con clave' : 'Sin clave'}</span>
            {prueba.limite && <span className="chip">Límite diario: {prueba.limite} créditos</span>}
            {prueba.restantes && <span className={`chip ${Number(prueba.restantes) < 150 ? 'acido' : ''}`}>Quedan hoy: {prueba.restantes}</span>}
            {horas != null && <span className="chip">Se renueva en {horas} h</span>}
          </div>
        )}
      </div>
    </div>
  )
}

function PanelTunel({ l, set }) {
  const avisar = useAviso()
  const [t, setT] = useState(null)
  usePeriodico(async () => { try { setT(await api.get('/api/tunel')) } catch { /* */ } }, 2500)
  const accion = async (acc) => {
    try { await api.put('/api/ajustes', { literatura: { tunel: l.tunel, tor_puentes: l.tor_puentes, tor_puentes_propios: l.tor_puentes_propios, tor_salida: l.tor_salida } }); setT(await api.post(`/api/tunel/${acc}`)) }
    catch (e) { avisar(e.message, 'error') }
  }
  return (
    <div className="caja">
      <div className="caja-cab"><span className="num">VPN</span>Túnel de privacidad para literatura</div>
      <div className="caja-cuerpo col">
        <div className="tenue" style={{ fontSize: 12.5 }}>Solo afecta a búsquedas y descargas de literatura (OpenAlex, Sci-Hub, LibGen, Anna's Archive). La IA y las noticias usan tu conexión normal. No necesita permisos de administrador.</div>
        <div className="grupo-btn" style={{ width: 'fit-content' }}>
          {[['directo', 'Directo'], ['tor', 'Tor integrado (código abierto)'], ['proxy', 'Proxy de mi VPN']].map(([k, txt]) => (
            <button key={k} className={`btn ${l.tunel === k ? 'activo' : ''}`} disabled={k === 'tor' && t && !t.disponible} onClick={() => set('literatura', 'tunel', k)}>{txt}</button>
          ))}
        </div>
        {l.tunel === 'tor' && (
          <div className="form-rejilla">
            <Campo etiqueta="Estado">
              <div className="fila">
                <span className="tunel-chip"><span className={`luz ${t?.estado}`} />{t?.estado === 'listo' ? 'Conectado' : t?.estado === 'iniciando' ? `Conectando ${t.progreso}%` : t?.estado === 'error' ? 'Error' : 'Apagado'}</span>
                {t?.estado === 'listo' || t?.estado === 'iniciando'
                  ? <button className="btn chico" onClick={() => accion('detener')}>Detener</button>
                  : <button className="btn chico primario" onClick={() => accion('iniciar')}>Conectar ahora</button>}
              </div>
              {t?.mensaje && <small className="mono">{t.mensaje}</small>}
            </Campo>
            <Campo etiqueta="Puentes (si tu red bloquea Tor)">
              <select className="entrada" value={l.tor_puentes} onChange={(e) => set('literatura', 'tor_puentes', e.target.value)}>
                <option value="ninguno">Sin puentes</option><option value="snowflake">Snowflake (recomendado si hay bloqueo)</option>
                <option value="obfs4">obfs4 integrados</option><option value="propios">Mis puentes</option>
              </select>
            </Campo>
            {l.tor_puentes === 'propios' && (
              <Campo etiqueta="Líneas de puente" ancho ayuda="Pégalas desde bridges.torproject.org, una por línea.">
                <textarea className="entrada" rows={4} value={l.tor_puentes_propios} onChange={(e) => set('literatura', 'tor_puentes_propios', e.target.value)} placeholder="obfs4 1.2.3.4:443 FINGERPRINT cert=… iat-mode=0" />
              </Campo>
            )}
            <Campo etiqueta="Países de salida (opcional)" ayuda="Códigos ISO separados por comas, p. ej. de,nl,ch.">
              <input className="entrada mono" value={l.tor_salida} onChange={(e) => set('literatura', 'tor_salida', e.target.value)} />
            </Campo>
          </div>
        )}
        {l.tunel === 'proxy' && (
          <div className="form-rejilla">
            <Campo etiqueta="Tipo de proxy"><select className="entrada" value={l.proxy_tipo} onChange={(e) => set('literatura', 'proxy_tipo', e.target.value)}><option value="socks5">SOCKS5</option><option value="http">HTTP</option></select></Campo>
            <Campo etiqueta="Servidor : puerto" ayuda="Muchas VPN exponen un proxy local (p. ej. Mysterium, Proton, Mullvad con SOCKS5).">
              <div style={{ display: 'flex', gap: 8 }}><input className="entrada mono" value={l.proxy_host} onChange={(e) => set('literatura', 'proxy_host', e.target.value)} /><input className="entrada mono" style={{ width: 100 }} value={l.proxy_puerto} onChange={(e) => set('literatura', 'proxy_puerto', e.target.value)} /></div>
            </Campo>
            <Campo etiqueta="Usuario (opcional)"><input className="entrada" value={l.proxy_usuario} onChange={(e) => set('literatura', 'proxy_usuario', e.target.value)} /></Campo>
            <Campo etiqueta="Contraseña (opcional)"><input className="entrada" type="password" placeholder={l.proxy_clave_configurada ? '•••• guardada' : ''} value={l.proxy_clave} onChange={(e) => set('literatura', 'proxy_clave', e.target.value)} /></Campo>
          </div>
        )}
        <div className="tenue" style={{ fontSize: 12 }}>Guarda los ajustes para aplicar el modo. Tor es más lento en descargas grandes.</div>
      </div>
    </div>
  )
}

function ListaEditable({ valores = [], onChange, placeholder }) {
  return (
    <div className="col" style={{ gap: 6 }}>
      {valores.map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <input className="entrada mono" style={{ fontSize: 12 }} value={v} onChange={(e) => onChange(valores.map((x, j) => (j === i ? e.target.value : x)))} />
          <button className="btn icono" onClick={() => onChange(valores.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
        </div>
      ))}
      <button className="btn chico" style={{ width: 'fit-content' }} onClick={() => onChange([...valores, ''])}><Plus size={13} />{placeholder ? 'Añadir' : 'Añadir'}</button>
    </div>
  )
}

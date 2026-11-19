// Cliente mínimo de la API local
async function req(metodo, ruta, cuerpo) {
  const opts = { method: metodo, headers: {} }
  if (cuerpo instanceof FormData) opts.body = cuerpo
  else if (cuerpo !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(cuerpo)
  }
  const r = await fetch(ruta, opts)
  const tipo = r.headers.get('content-type') || ''
  const datos = tipo.includes('application/json') ? await r.json() : await r.text()
  if (!r.ok) throw new Error((datos && datos.detail) || `Error HTTP ${r.status}`)
  return datos
}

export const api = {
  get: (r) => req('GET', r),
  post: (r, c = {}) => req('POST', r, c),
  put: (r, c) => req('PUT', r, c),
  patch: (r, c) => req('PATCH', r, c),
  del: (r) => req('DELETE', r),
}

export const qs = (o) =>
  '?' + Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')

export const abrirUrl = (url) => api.post('/api/abrir-url', { url })
export const abrirRuta = (ruta, mostrar = false) => api.post('/api/abrir-ruta', { ruta, mostrar })

export async function dialogoNativo(tipo = 'abrir', extra = {}) {
  try {
    const r = await api.post('/api/dialogo', { tipo, ...extra })
    return r.rutas
  } catch (e) {
    if (String(e.message).includes('no disponible')) return null // estamos en navegador
    throw e
  }
}

export const IDIOMAS_UI = {
  es: 'Español', en: 'Inglés', pt: 'Portugués', fr: 'Francés', de: 'Alemán', it: 'Italiano',
  zh: 'Chino simpl.', 'zh-TW': 'Chino trad.', ja: 'Japonés', ko: 'Coreano', ru: 'Ruso',
}

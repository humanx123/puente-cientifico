import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/700.css'
import '@fontsource/archivo-black/400.css'
import './styles.css'
import App from './App.jsx'
import { ProveedorAvisos } from './ui.jsx'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ProveedorAvisos>
      <App />
    </ProveedorAvisos>
  </React.StrictMode>,
)

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// En desarrollo, /api se redirige al servidor Python (python backend/run.py --navegador)
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../backend/static', emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8777' } },
})

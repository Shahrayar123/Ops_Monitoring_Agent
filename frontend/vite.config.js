import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies /api -> the FastAPI backend, so the frontend makes
// same-origin calls (no CORS headaches in dev) and the same relative URLs keep
// working when both are served behind one reverse proxy in production.
//
// Backend URL defaults to port 8000. Override it without editing this file by
// setting BACKEND_URL before `npm run dev`, e.g.:
//   PowerShell:  $env:BACKEND_URL="http://127.0.0.1:8090"; npm run dev
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})

/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend runs on :8000 (uvicorn chamapro.api.main:app). Proxying
// /api keeps the dashboard same-origin, so the browser needs no CORS and the
// microphone works on http://localhost.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
  // The reduced-motion test reads the global stylesheet; other CSS stays stubbed in tests.
  test: { css: { include: [/index\.css/] } },
})

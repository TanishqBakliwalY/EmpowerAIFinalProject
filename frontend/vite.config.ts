import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run build` writes frontend/dist, which the FastAPI server serves at http://127.0.0.1:8000.
// `npm run dev` (port 5173) is only for editing the UI; it proxies /api to the running backend.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})

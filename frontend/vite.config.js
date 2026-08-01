import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/datasets': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/clean': 'http://127.0.0.1:8000',
      '/examples': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/feedback': 'http://127.0.0.1:8000',
    },
  },
})

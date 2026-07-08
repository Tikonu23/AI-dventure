import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8123',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // A turn can run several sequential Claude calls (tool loop) before
        // turn_complete, so give the proxy generous headroom rather than
        // risk it cutting the SSE connection short on a slow turn.
        proxyTimeout: 120_000,
        timeout: 120_000,
      },
    },
  },
})

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
        // No proxy timeouts: /games/{id}/events is an indefinite SSE stream.
        // sse-starlette's keepalive pings hold the socket open, and if a hop
        // still cuts it, EventSource auto-reconnects and the app refetches
        // the snapshot — but don't invite that churn with a local timeout.
      },
    },
  },
})

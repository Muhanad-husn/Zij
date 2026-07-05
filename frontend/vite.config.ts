import { defineConfig } from 'vite';

// ADR-7 / spec §2 "Build": dev proxies /api (incl. /api/events SSE) to the
// FastAPI process. Slice 01 makes no API calls, but the proxy is wired now so
// later slices need no config churn. ws:false — SSE is a streaming HTTP GET,
// not a websocket (ADR-2).
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: false },
    },
  },
});

import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { defineConfig, type Plugin } from 'vite'

const API = process.env.GEOINTX_API ?? 'http://127.0.0.1:8000'

// MapLibre GL v6 starts its web worker from `./maplibre-gl-worker.mjs` relative to the
// bundle (which in turn imports `./maplibre-gl-shared.mjs`). Ship both next to the
// built JS so the worker resolves in production.
function maplibreWorker(): Plugin {
  const dist = dirname(createRequire(import.meta.url).resolve('maplibre-gl/dist/maplibre-gl.mjs'))
  return {
    name: 'maplibre-worker',
    apply: 'build',
    generateBundle() {
      for (const f of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']) {
        this.emitFile({ type: 'asset', fileName: `assets/${f}`, source: readFileSync(join(dist, f)) })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), maplibreWorker()],
  // Serve maplibre from its own dist folder in dev so the worker sits beside it.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  server: {
    port: 5173,
    proxy: {
      '/api': API,
      '/artifacts': API,
    },
  },
  build: {
    chunkSizeWarningLimit: 1500,
  },
})

/// <reference types="vitest/config" />
import { configDefaults } from 'vitest/config'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the React app runs on Vite (port 5173) and sends /api to the FastAPI server (port 8600).
// In production FastAPI serves the built files from web/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8600', changeOrigin: false } },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Mantine in its own file (cached across releases); ECharts is split by the chart renderer itself,
        // which loads only the chart types a page draws
        manualChunks: { mantine: ['@mantine/core', '@mantine/hooks'] },
      },
    },
  },
  test: { exclude: [...configDefaults.exclude, 'e2e/**'] },  // e2e/ is Playwright's (npx playwright test)
})

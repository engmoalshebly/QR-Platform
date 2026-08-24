import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'node:url'

// Works with Vite's native config loader as well as the default bundler. This
// avoids relying on CommonJS-only __dirname when running the local server.
const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query', 'zustand'],
          forms: ['react-hook-form', 'zod', '@hookform/resolvers'],
          graphics: ['framer-motion', 'lucide-react', 'qrcode'],
          spreadsheet: ['exceljs'],
        },
      },
    },
    chunkSizeWarningLimit: 350,
  },
  resolve: {
    alias: {
      '@':          path.resolve(rootDir, './src'),
      '@app':       path.resolve(rootDir, './src/app'),
      '@components': path.resolve(rootDir, './src/components'),
      '@design':    path.resolve(rootDir, './src/design'),
      '@features':  path.resolve(rootDir, './src/features'),
      '@shared':    path.resolve(rootDir, './src/shared'),
      '@services':  path.resolve(rootDir, './src/services'),
      '@assets':    path.resolve(rootDir, './src/assets'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 8000 is occupied by the local Supabase gateway.  FastAPI for this
        // workspace intentionally runs on 8021 (see start.ps1).
        target: 'http://127.0.0.1:8021',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path,
      },
    },
    headers: {
      // The management interface must never become a camera-capable surface.
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    },
  },
})

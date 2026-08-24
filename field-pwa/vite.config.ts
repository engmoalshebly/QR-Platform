import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // The PWA is deployed by FastAPI under the camera-permitted /field/ route.
  // Vite also serves this base during development at http://localhost:5174/field/.
  base: '/field/',
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          query: ['@tanstack/react-query'],
          scanner: ['@zxing/browser', '@zxing/library'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8021',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})

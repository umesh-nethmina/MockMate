import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // The Monaco editor chunk (~850 kB gzipped) is lazy-loaded only for coding interviews.
    chunkSizeWarningLimit: 3500,
  },
})

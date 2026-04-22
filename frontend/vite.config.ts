/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/analytica/',
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      '/analytica/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/analytica/, ''),
      },
      '/analytica/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        rewrite: (path) => path.replace(/^\/analytica/, ''),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
  },
})

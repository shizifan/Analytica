/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const pkg = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf-8'))

export default defineConfig({
  base: '/analytica/',
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'redirect-base',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/analytica') {
            res.writeHead(301, { Location: '/analytica/' })
            res.end()
            return
          }
          next()
        })
      },
    },
  ],
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

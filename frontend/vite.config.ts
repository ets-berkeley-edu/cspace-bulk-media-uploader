import {URL, fileURLToPath} from 'node:url'
import vue from '@vitejs/plugin-vue'
import vuetify, {transformAssetUrls} from 'vite-plugin-vuetify'
import {defineConfig} from 'vitest/config'

// In development the Vue app runs on :5173 and forwards /api to the FastAPI app.
export default defineConfig({
  plugins: [
    vue({
      template: {transformAssetUrls}
    }),
    // Components are registered by hand in src/plugins/vuetify.ts, as in BOA.
    vuetify({
      autoImport: false
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: true,
    port: 5173,
    proxy: {'/api': {target: process.env.VITE_API_TARGET || 'http://localhost:8000', changeOrigin: false}}
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/browser.ts', './src/__tests__/setup.ts'],
    server: {deps: {inline: ['vuetify']}}
  }
})

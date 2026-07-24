import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ['@fortune-sheet/react', '@fortune-sheet/core'],
  },
  build: {
    // Прод-бандл без sourcemap: не раздувает статику и не утекает исходники.
    // Для локальной отладки можно временно вернуть 'hidden'.
    sourcemap: false,
    rollupOptions: {
      output: {
        // Тяжёлые библиотеки — в отдельные vendor-чанки: стабильные имена лучше
        // кэшируются между релизами и не тянутся в чанки, где не нужны.
        manualChunks: {
          recharts: ['recharts'],
          xlsx: ['xlsx'],
          'fortune-sheet': ['@fortune-sheet/react', '@fortune-sheet/core'],
          'react-data-grid': ['react-data-grid'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})

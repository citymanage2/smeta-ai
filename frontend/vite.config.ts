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
    // Тесты рисуют компоненты в jsdom и ждут перерисовки через `waitFor`.
    // Дефолтных 5 секунд хватает только на свободной машине: когда рядом
    // работает IDE или второй прогон, ожидания не укладываются в срок и тесты
    // падают пачками в случайных файлах, хотя код исправен. Пятнадцать секунд
    // ничего не замедляют — при зелёном тесте ожидание кончается раньше.
    testTimeout: 15_000,
    hookTimeout: 15_000,
    poolOptions: {
      // По умолчанию vitest берёт почти все ядра, и файлы отнимают время друг
      // у друга: тяжёлые тесты редактора (2000 строк) упираются в таймаут не
      // потому, что медленные, а потому что им не досталось процессора.
      forks: { maxForks: 4 },
    },
  },
})

import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      // 捕获所有以 /api 开头的请求
      '/api': {
        target: 'http://127.0.0.1:8001', // 转发给后端 API
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '') // 去掉 /api 前缀 (如果后端接口没这个前缀)
        // 注意：我们的 FastAPI 路由是 /tasks，没有 /api 前缀
        // 所以这里 rewrite 很重要：前端发 /api/tasks -> 后端收 /tasks
      }
    }
  }
})

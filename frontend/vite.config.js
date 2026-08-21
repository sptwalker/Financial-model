import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api 反代到本地 FastAPI；生产由 nginx 承担
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5185,          // 固定端口，避开工作区其它项目的开发服务器
    strictPort: true,    // 被占用则报错，绝不静默漂移到别的端口
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})

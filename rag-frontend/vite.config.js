import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite' // 🌟 新增这一行

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(), // 🌟 新增这一行
  ],
})
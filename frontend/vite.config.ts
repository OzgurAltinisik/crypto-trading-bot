import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// `npm run dev` serves the UI on :5173 and proxies /api to the FastAPI server on :8000.
// `npm run build` writes to ../cryptobot/web/dist, which `python -m cryptobot serve` serves.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "../cryptobot/web/dist", emptyOutDir: true },
})

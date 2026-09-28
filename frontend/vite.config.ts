import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// In development the Vue app runs on :5173 and forwards /api to the FastAPI app.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: false } },
  },
  test: { environment: "jsdom" },
});

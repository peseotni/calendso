import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// During development the API runs on :8000 (python -m audiobook_studio).
const backend = process.env.STUDIO_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/feeds": backend,
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1000,
  },
});

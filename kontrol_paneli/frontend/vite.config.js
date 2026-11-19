import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirme sunucusu (npm run dev, :5173) API isteklerini Python arka ucuna (:8090) yönlendirir.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8090" } },
});

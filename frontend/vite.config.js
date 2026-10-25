import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },   // dev: frontend talks to FastAPI (make api)
  // Two pages: the web app (index.html -> src/App.jsx) and the phone app (app.html -> src/app/PhoneApp.jsx).
  build: { rollupOptions: { input: { main: "index.html", app: "app.html" } } },
});

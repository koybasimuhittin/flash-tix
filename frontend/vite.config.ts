import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: API calls go to the nginx gateway in compose.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});

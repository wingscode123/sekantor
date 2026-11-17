import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built straight into the Python package so `sekantor up` serves it (src/sekantor/hub/static is gitignored).
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "../src/sekantor/hub/static", emptyOutDir: true },
  server: {
    // `npm run dev` proxies the API to a running `sekantor up`. Open http://127.0.0.1:7878/?token=... once
    // first so the cookie exists.
    proxy: { "/v1": { target: "http://127.0.0.1:7878", ws: true, changeOrigin: false } },
  },
});

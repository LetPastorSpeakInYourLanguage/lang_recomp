import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to `python -m app --serve` (port 8765).
export default defineConfig({
  plugins: [react()],
  // 127.0.0.1 explicitly: on Windows "localhost" may bind IPv6 only, which other
  // tools (and the API proxy's own checks) then cannot reach.
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: { "/api": "http://127.0.0.1:8765" } },
});

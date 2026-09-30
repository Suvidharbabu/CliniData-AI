import { resolve } from "node:path";
import { defineConfig } from "vite";

const pages = [
  "index", "platform", "architecture", "agents", "codebook", "security",
  "roadmap", "contact", "login", "demo", "approvals",
];

export default defineConfig({
  // Read VITE_* variables from the repo-root .env shared with the backend.
  envDir: resolve(__dirname, ".."),
  build: {
    rollupOptions: {
      input: Object.fromEntries(pages.map((p) => [p, resolve(__dirname, `${p}.html`)])),
    },
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});

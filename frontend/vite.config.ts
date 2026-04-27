import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "redirect-root-to-ui",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const u = req.url?.split("?")[0] ?? "";
          if (u === "/" || u === "") {
            res.statusCode = 302;
            res.setHeader("Location", "/ui/");
            res.end();
            return;
          }
          next();
        });
      },
    },
  ],
  base: "/ui/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8768", changeOrigin: true },
      "/ui/legacy": { target: "http://127.0.0.1:8768", changeOrigin: true },
    },
  },
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
  },
});

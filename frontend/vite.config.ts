import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Renderer build. `base: "./"` makes asset paths relative so the bundle works
// when loaded from the local filesystem inside Electron.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});

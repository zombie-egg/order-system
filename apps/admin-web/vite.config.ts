import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Production builds pass `--base=/admin/` so the shared reverse proxy can serve
// this app under a path prefix.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
  },
});

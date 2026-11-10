import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Development: `python backend/app.py` on :3001 and `npm run dev` here (API proxied)
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://localhost:3002' } },
});

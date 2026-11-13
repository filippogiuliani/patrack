import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

// Development: `python backend/app.py` on :3001 and `npm run dev` here (API proxied)
export default defineConfig({
  plugins: [svelte()],
  // famkit/ui: what the family apps' frontends share (backend/famkit is a git submodule)
  resolve: { alias: { $famkit: fileURLToPath(new URL('../backend/famkit/ui', import.meta.url)) }, dedupe: ['svelte'] },
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: { fs: { allow: ['..'] }, proxy: { '/api': 'http://localhost:3002' } },
});

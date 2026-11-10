<script>
  import { app } from '../lib/store.svelte.js';
  async function act() {
    const a = app.toast?.action;
    app.toast = null;
    await a?.run();
  }
</script>

{#if app.toast}
  {#key app.toast.id}
    <div class="toast" class:err={app.toast.kind === 'error'} role="status">
      <span>{app.toast.message}</span>
      {#if app.toast.action}<button class="act" onclick={act}>{app.toast.action.label}</button>{/if}
    </div>
  {/key}
{/if}

<style>
  .toast {
    position: fixed; left: 50%; transform: translateX(-50%); z-index: 200;
    bottom: calc(var(--nav-h) + 20px + env(safe-area-inset-bottom));
    max-width: calc(100vw - 32px); padding: 10px 12px 10px 20px; border-radius: var(--r-xs);
    background: var(--ink); color: var(--bg); font-weight: 600; box-shadow: var(--shadow-lg);
    animation: pop 0.2s ease; display: flex; align-items: center; gap: 14px;
  }
  .toast:not(:has(.act)) { padding-right: 20px; }
  .toast.err { background: var(--danger); color: white; }
  .act { border: 0; background: none; color: var(--primary-soft); font: inherit; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.03em; font-size: 0.82rem; cursor: pointer; padding: 6px 8px; border-radius: var(--r-xs); }
  .act:hover { background: rgba(255, 255, 255, 0.12); }
  @media (min-width: 900px) { .toast { bottom: 28px; } }
</style>

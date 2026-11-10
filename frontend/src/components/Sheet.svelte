<script>
  // Modal panel: a bottom sheet on phones, a centered dialog on desktop
  import { t } from '../lib/i18n.svelte.js';
  let { title, onclose, children, footer, wide = false } = $props();

  $effect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => e.key === 'Escape' && onclose?.();
    window.addEventListener('keydown', onKey);
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey); };
  });
</script>

<div class="overlay" onclick={(e) => e.target === e.currentTarget && onclose?.()} role="presentation">
  <div class="sheet" class:wide role="dialog" aria-modal="true" aria-label={title}>
    <header>
      <span class="grip" aria-hidden="true"></span>
      <h2>{title}</h2>
      <button class="btn icon sm ghost" onclick={onclose} aria-label={t("common.close")}>✕</button>
    </header>
    <div class="body">{@render children()}</div>
    {#if footer}<footer>{@render footer()}</footer>{/if}
  </div>
</div>

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 100;
    background: rgba(17, 24, 39, 0.4);
    display: flex; align-items: flex-end; justify-content: center;
    animation: fade 0.15s ease;
  }
  .sheet {
    width: 100%; max-height: 94dvh; display: flex; flex-direction: column;
    background: var(--surface); border-radius: 14px 14px 0 0; box-shadow: var(--shadow-lg);
    animation: up 0.22s cubic-bezier(0.2, 0.9, 0.3, 1.1);
  }
  header { position: relative; display: flex; align-items: center; gap: 10px; padding: 22px 16px 10px 20px; }
  header h2 { flex: 1; }
  .grip { position: absolute; top: 8px; left: 50%; width: 42px; height: 5px; margin-left: -21px; border-radius: 9px; background: var(--line); }
  .body { overflow-y: auto; padding: 6px 20px 20px; overscroll-behavior: contain; }
  footer {
    display: flex; gap: 10px; padding: 12px 20px calc(12px + env(safe-area-inset-bottom));
    border-top: 1px solid var(--line); background: var(--surface); border-radius: 0 0 14px 14px;
  }
  @media (min-width: 900px) {
    .overlay { align-items: center; padding: 24px; }
    .sheet { max-width: 560px; border-radius: var(--r-sm); max-height: 88dvh; animation: pop 0.18s ease; }
    .sheet.wide { max-width: 760px; }
    .grip { display: none; }
    header { padding-top: 18px; }
  }
  @keyframes up { from { transform: translateY(40px); opacity: 0; } to { transform: none; opacity: 1; } }
  @keyframes fade { from { opacity: 0; } }
</style>

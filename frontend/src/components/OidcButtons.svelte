<script>
  // "Continue with …" buttons for the OIDC providers configured on the server
  import { app } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let { invite = null } = $props();
  const providers = $derived(app.me?.oidc ?? []);
  const href = (p) => `/api/oidc/${encodeURIComponent(p.id)}/login${invite ? `?invite=${encodeURIComponent(invite)}` : ''}`;
</script>

{#if providers.length}
  <div class="stack oidc">
    {#each providers as p (p.id)}
      <a class="btn block" href={href(p)}>{t('auth.continue_with', { provider: p.name })}</a>
    {/each}
    {#if app.me?.password_login !== false}<div class="sep"><span>{t('auth.or')}</span></div>{/if}
  </div>
{/if}

<style>
  .oidc { gap: 8px; }
  .sep { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 0.8rem; margin: 6px 0 2px; }
  .sep::before, .sep::after { content: ''; flex: 1; height: 1px; background: var(--line); }
</style>

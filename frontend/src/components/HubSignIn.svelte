<script>
  // Sign-in when the family is managed in weHub: one button to the provider (Pocket ID), followed automatically
  // unless we just came back with an error (so a refusal never loops).
  import { app } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let { error = '' } = $props();
  const provider = $derived(app.me?.oidc?.[0]);
  const href = $derived(provider ? `/api/oidc/${encodeURIComponent(provider.id)}/login` : null);
  let going = $state(false);
  $effect(() => {
    // Coming back with an error (e.g. no access): stay here, never loop
    if (!href || error || /[?&]error=/.test(location.hash)) return;
    let tried = false;
    try { tried = sessionStorage.getItem('hub.signin') === '1'; sessionStorage.setItem('hub.signin', '1'); } catch { /* ignore */ }
    if (tried) return; // second visit in a row: let the person choose
    going = true;
    location.href = href;
  });
</script>

<div class="stack hub">
  {#if error}<p class="err small" role="alert">{error}</p>{/if}
  {#if href}
    <a class="btn primary block" href={href} onclick={() => { try { sessionStorage.removeItem('hub.signin'); } catch { /* ignore */ } }}>
      {going ? t('hub.redirecting') : t('hub.sign_in')}</a>
    <p class="tiny muted">{t('hub.sign_in_note')}</p>
    {#if app.me.hub.url}<a class="small" href={app.me.hub.url}>{t('hub.open')}</a>{/if}
  {:else}
    <p class="small muted">{t('auth.no_sign_in')}</p>
  {/if}
</div>

<style>
  .hub { text-align: center; }
  .err { color: var(--danger); font-weight: 500; }
</style>

<script>
  import { onMount } from 'svelte';
  import { post } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  let { token, ondone } = $props();
  let status = $state('waiting');
  let error = $state('');
  onMount(async () => {
    try { await post('/verify-email', { token }); status = 'ok'; await ondone?.(); }
    catch (e) { status = 'error'; error = e.message; }
  });
</script>

<AuthCard title={t('auth.verify_title')}>
  {#if status === 'waiting'}<p class="muted">{t('common.wait')}</p>
  {:else if status === 'ok'}<p>{t('auth.verify_ok')}</p><a class="btn primary" href="#/">{t('auth.go_to_app')}</a>
  {:else}<p class="err">{error}</p><a class="btn" href="#/">{t('auth.go_to_app')}</a>{/if}
</AuthCard>

<style>.err { color: var(--danger); }</style>

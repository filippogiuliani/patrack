<script>
  import { post } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  let { token, ondone } = $props();
  let password = $state('');
  let confirmation = $state('');
  let error = $state('');
  let sending = $state(false);
  async function submit(e) {
    e.preventDefault();
    if (password !== confirmation) { error = t('auth.passwords_differ'); return; }
    sending = true; error = '';
    try { await post('/reset-password', { token, password }); await ondone(); } catch (err) { error = err.message; } finally { sending = false; }
  }
</script>

<AuthCard title={t('auth.new_password')}>
  <form class="stack" onsubmit={submit}>
    <label class="field"><span class="label">{t('auth.new_password')}</span>
      <input class="input" type="password" bind:value={password} autocomplete="new-password" required minlength="8" /></label>
    <label class="field"><span class="label">{t('auth.repeat_password')}</span>
      <input class="input" type="password" bind:value={confirmation} autocomplete="new-password" required minlength="8" /></label>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    <button class="btn primary block" disabled={sending}>{t('auth.save_password')}</button>
  </form>
</AuthCard>

<style>.err { color: var(--danger); font-weight: 500; }</style>

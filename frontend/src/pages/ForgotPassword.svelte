<script>
  import { post } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  let email = $state('');
  let sent = $state(false);
  let error = $state('');
  async function submit(e) {
    e.preventDefault();
    error = '';
    try { await post('/forgot-password', { email }); sent = true; } catch (err) { error = err.message; }
  }
</script>

<AuthCard title={t('auth.recover_title')} subtitle={sent ? '' : t('auth.recover_subtitle')}>
  {#if sent}
    <p>{t('auth.recover_sent', { email })}</p>
    <a class="btn" href="#/login">{t('auth.back_to_sign_in')}</a>
  {:else}
    <form class="stack" onsubmit={submit}>
      <label class="field"><span class="label">{t('auth.email')}</span>
        <input class="input" type="email" bind:value={email} autocomplete="email" required /></label>
      {#if error}<p class="err small" role="alert">{error}</p>{/if}
      <button class="btn primary block">{t('auth.send_link')}</button>
      <a class="small" href="#/login">{t('auth.back_to_sign_in')}</a>
    </form>
  {/if}
</AuthCard>

<style>.err { color: var(--danger); font-weight: 500; }</style>

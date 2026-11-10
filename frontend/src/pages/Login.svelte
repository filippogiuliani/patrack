<script>
  import { post } from '../lib/api.js';
  import { app } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  import OidcButtons from '../components/OidcButtons.svelte';
  import HubSignIn from '../components/HubSignIn.svelte';
  // embedded: used inside another page (e.g. an invitation), without the frame
  let { ondone, embedded = false, invite = null, initialError = '' } = $props();
  let email = $state('');
  let password = $state('');
  let error = $state('');
  let sending = $state(false);
  let step = $state('password'); // password | code (two-step verification)
  let code = $state('');
  $effect(() => { if (initialError) error = initialError; });

  async function signIn(e) {
    e.preventDefault();
    sending = true; error = '';
    try {
      const r = await post('/login', { email, password });
      if (r.two_factor) { step = 'code'; code = ''; return; }
      await ondone();
    }
    catch (err) { error = err.message; password = ''; }
    finally { sending = false; }
  }
  async function sendCode(e) {
    e.preventDefault();
    sending = true; error = '';
    try { await post('/login/2fa', { code }); await ondone(); }
    catch (err) { error = err.message; code = ''; if (/scadut|expired/i.test(err.message)) step = 'password'; }
    finally { sending = false; }
  }
</script>

{#snippet form()}
  {#if app.me?.hub}
  <HubSignIn {error} />
  {:else}
  {#if step === 'code'}
  <form class="stack" onsubmit={sendCode}>
    <p class="small">{t('twofa.login_prompt')}</p>
    <label class="field"><span class="label">{t('twofa.code')}</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input class="input code" bind:value={code} inputmode="numeric" autocomplete="one-time-code" maxlength="9" autofocus required /></label>
    <p class="tiny muted">{t('twofa.login_recovery')}</p>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    <button class="btn primary block" disabled={sending || !code.trim()}>{sending ? t('auth.signing_in') : t('twofa.confirm')}</button>
    <button type="button" class="btn ghost block" onclick={() => { step = 'password'; error = ''; }}>{t('common.back')}</button>
  </form>
  {:else}
  <OidcButtons {invite} />
  {#if app.me?.password_login === false}
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    {#if !app.me?.oidc?.length}<p class="small muted">{t('auth.no_sign_in')}</p>{/if}
  {:else}
  <form class="stack" onsubmit={signIn}>
    <label class="field"><span class="label">{t('auth.email')}</span>
      <input class="input" type="email" bind:value={email} autocomplete="email" required /></label>
    <label class="field"><span class="label">{t('auth.password')}</span>
      <input class="input" type="password" bind:value={password} autocomplete="current-password" required /></label>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    <button class="btn primary block" disabled={sending}>{sending ? t('auth.signing_in') : t('auth.sign_in')}</button>
    {#if !embedded}
      <div class="spread small">
        <a href="#/forgot-password">{t('auth.forgot_password')}</a>
        <a href="#/signup">{t('auth.create_account')}</a>
      </div>
    {/if}
  </form>
  {/if}
  {/if}
  {/if}
{/snippet}

{#if embedded}
  {@render form()}
{:else}
  <AuthCard title={t('auth.sign_in')} subtitle={t('auth.subtitle')}>{@render form()}</AuthCard>
{/if}

<style>
  .err { color: var(--danger); font-weight: 500; }
  .code { font-size: 1.3rem; letter-spacing: 0.2em; text-align: center; font-family: ui-monospace, monospace; }
</style>

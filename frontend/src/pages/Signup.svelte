<script>
  import { onMount } from 'svelte';
  import { get, post } from '../lib/api.js';
  import { app } from '../lib/store.svelte.js';
  import { language, t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  import OidcButtons from '../components/OidcButtons.svelte';

  // external: completing sign-up after signing in with an OIDC provider; invite: invitation token
  let { ondone, embedded = false, invite = null, external = false, inviteFamily = null } = $props();
  let name = $state('');
  let email = $state('');
  let password = $state('');
  let consent = $state(false);
  let error = $state('');
  let sending = $state(false);
  let pending = $state(null);

  onMount(async () => {
    if (!external) return;
    try { pending = await get('/oidc/pending'); name = pending.name; }
    catch (e) { error = e.message; }
  });

  const withInvite = $derived(!!invite || !!pending?.invite);

  async function submit(e) {
    e.preventDefault();
    sending = true; error = '';
    const common = { name, consent, language: language.id };
    try {
      if (external) await post('/oidc/complete', common);
      else await post('/signup', { ...common, email, password, invite });
      await ondone();
    } catch (err) { error = err.message; }
    finally { sending = false; }
  }
</script>

{#snippet form()}
  {#if !external}<OidcButtons {invite} />{/if}
  {#if !external && app.me?.password_login === false}
    {#if !embedded}<p class="small center">{t('auth.have_account')} <a href="#/login">{t('auth.sign_in')}</a></p>{/if}
  {:else}
  <form class="stack" onsubmit={submit}>
    {#if external && pending}
      <p class="small info">{t('auth.external_info', { provider: pending.provider, email: pending.email })}</p>
    {/if}
    <label class="field"><span class="label">{t('auth.your_name')}</span>
      <input class="input" bind:value={name} autocomplete="given-name" required maxlength="80" /></label>
    {#if !external}
      <label class="field"><span class="label">{t('auth.email')}</span>
        <input class="input" type="email" bind:value={email} autocomplete="email" required /></label>
      <label class="field"><span class="label">{t('auth.password')}</span>
        <input class="input" type="password" bind:value={password} autocomplete="new-password" required minlength="8" />
        <span class="tiny muted">{t('auth.password_rules')}</span></label>
    {/if}
    {#if withInvite && inviteFamily}
      <p class="small info">{t('auth.you_will_join', { family: inviteFamily })}</p>
    {/if}
    <label class="consent small">
      <input type="checkbox" bind:checked={consent} required />
      <span>{t('auth.consent_before')} <a href="#/privacy" target="_blank">{t('auth.privacy_notice')}</a>{t('auth.consent_after')}</span>
    </label>
    {#if error}<p class="err small" role="alert">{error}</p>{/if}
    <button class="btn primary block" disabled={sending || !consent}>{sending ? t('common.wait') : t('auth.create_account')}</button>
    {#if !embedded}<p class="small center">{t('auth.have_account')} <a href="#/login">{t('auth.sign_in')}</a></p>{/if}
  </form>
  {/if}
{/snippet}

{#if embedded}
  {@render form()}
{:else if !app.me?.signup_open && !invite && !external}
  <AuthCard title={t('auth.create_account')}><p>{t('auth.invite_only')}</p><a class="btn" href="#/login">{t('auth.sign_in')}</a></AuthCard>
{:else}
  <AuthCard title={external ? t('auth.complete') : t('auth.create_account')} subtitle={t('auth.signup_subtitle')}>{@render form()}</AuthCard>
{/if}

<style>
  .err { color: var(--danger); font-weight: 500; }
  .info { padding: 10px 12px; border-radius: var(--r-sm); background: var(--primary-soft); color: var(--ink); }
  .consent { display: flex; gap: 10px; align-items: flex-start; line-height: 1.4; cursor: pointer; }
  .consent input { margin-top: 3px; width: 16px; height: 16px; accent-color: var(--primary); flex-shrink: 0; }
  .center { text-align: center; }
</style>

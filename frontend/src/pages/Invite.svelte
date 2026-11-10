<script>
  import { onMount } from 'svelte';
  import { get, post } from '../lib/api.js';
  import { app, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import AuthCard from '../components/AuthCard.svelte';
  import Login from './Login.svelte';
  import Signup from './Signup.svelte';

  let { token, ondone } = $props();
  let info = $state(null);
  let error = $state('');
  let mode = $state('signup');

  onMount(async () => {
    try { info = await get(`/invites/${encodeURIComponent(token)}`); } catch (e) { error = e.message; }
  });

  async function accept() {
    try {
      await post(`/invites/${encodeURIComponent(token)}/accept`);
      toast(t('invite.welcome', { family: info.family }));
      await ondone();
      location.hash = '#/agenda';
    } catch (e) { error = e.message; }
  }
  // After signing in the user stays on this page to accept
  const afterLogin = async () => { await ondone(); };
</script>

<AuthCard title={t('invite.title')}>
  {#if error}
    <p class="err">{error}</p>
    <a class="btn" href="#/">{t('auth.go_to_app')}</a>
  {:else if !info}
    <p class="muted">{t('common.wait')}</p>
  {:else}
    <p>{info.invited_by ? t('invite.text_from', { name: info.invited_by, family: info.family }) : t('invite.text', { family: info.family })}</p>
    {#if app.me?.authenticated}
      {#if info.already_member}
        <p class="muted small">{t('invite.already_member')}</p>
        <a class="btn primary" href="#/agenda">{t('auth.go_to_app')}</a>
      {:else}
        <p class="muted small">{t('invite.how', { name: app.me.user.name, email: app.me.user.email })}</p>
        <button class="btn primary" onclick={accept}>{t('invite.accept')}</button>
      {/if}
    {:else}
      <div class="seg">
        <button class:on={mode === 'signup'} onclick={() => (mode = 'signup')}>{t('invite.new_here')}</button>
        <button class:on={mode === 'login'} onclick={() => (mode = 'login')}>{t('invite.have_account')}</button>
      </div>
      {#if mode === 'login'}
        <Login embedded invite={token} ondone={afterLogin} />
      {:else}
        <Signup embedded invite={token} inviteFamily={info.family} ondone={async () => { await ondone(); location.hash = '#/agenda'; }} />
      {/if}
    {/if}
  {/if}
</AuthCard>

<style>.err { color: var(--danger); }</style>

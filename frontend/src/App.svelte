<script>
  import { get, post, setUnauthorizedHandler } from './lib/api.js';
  import { app, loadMe, showError, toast } from './lib/store.svelte.js';
  import { language, setLanguage, t } from './lib/i18n.svelte.js';
  import { failedUploads, pendingUploads, sendFiles, uploads } from './lib/uploads.svelte.js';
  import AppSwitcher from '$famkit/AppSwitcher.svelte';
  import Toast from './components/Toast.svelte';
  import Icon from './components/Icon.svelte';
  import DocSheet from './components/DocSheet.svelte';
  import Scanner from './components/Scanner.svelte';
  import LanguageSwitch from './components/LanguageSwitch.svelte';
  import Login from './pages/Login.svelte';
  import Signup from './pages/Signup.svelte';
  import ForgotPassword from './pages/ForgotPassword.svelte';
  import ResetPassword from './pages/ResetPassword.svelte';
  import VerifyEmail from './pages/VerifyEmail.svelte';
  import Invite from './pages/Invite.svelte';
  import Privacy from './pages/Privacy.svelte';
  import Archive from './pages/Archive.svelte';
  import Imports from './pages/Imports.svelte';
  import Tax from './pages/Tax.svelte';
  import Family from './pages/Family.svelte';

  const NAV = ['archive', 'tax', 'imports', 'family'];
  // Pages reachable without an account
  const PUBLIC = ['login', 'signup', 'forgot-password', 'reset', 'verify', 'invite', 'privacy'];

  let status = $state('loading'); // loading | ready | error
  let route = $state(readHash());
  let lastSection = $state('archive');

  function readHash() {
    const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
    const [name = '', param = ''] = path.split('/');
    return { name, param: decodeURIComponent(param), query: new URLSearchParams(query) };
  }
  $effect(() => {
    const onHash = () => {
      const next = readHash();
      if (next.name !== 'doc' && next.name !== route.name) window.scrollTo(0, 0);
      route = next;
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  });

  const authenticated = $derived(!!app.me?.authenticated);
  const page = $derived.by(() => {
    if (!authenticated) return PUBLIC.includes(route.name) ? route.name : 'login';
    if (['verify', 'invite', 'privacy'].includes(route.name)) return route.name;
    if (route.name === 'doc') return lastSection; // the document opens over the page you were on
    return NAV.includes(route.name) ? route.name : 'archive';
  });
  $effect(() => { if (NAV.includes(page)) lastSection = page; });
  const openDoc = $derived(authenticated && route.name === 'doc' ? Number(route.param) : null);
  function closeDoc() {
    if (history.length > 1 && sessionStorage.getItem('patrack.inapp')) history.back();
    else location.hash = '#/' + lastSection;
  }
  // Remember that we navigated inside the app (so closing a document can go "back")
  $effect(() => { try { sessionStorage.setItem('patrack.inapp', '1'); } catch { /* ignore */ } });

  const fast = $derived(app.sync.active > 0 || pendingUploads() > 0);
  // Every few seconds while in view: has anything changed in the family, how is the import queue?
  $effect(() => {
    if (!authenticated) return;
    let busy = false;
    const tick = async () => {
      if (busy || document.visibilityState !== 'visible') return;
      busy = true;
      try {
        const s = await get('/sync');
        app.online = true;
        app.sync = { active: s.active, errors: s.errors };
        if (s.version !== app.version) app.version = s.version;
      } catch (e) {
        if (e.offline) app.online = false;
      } finally { busy = false; }
    };
    const onVisible = () => { if (document.visibilityState === 'visible') tick(); };
    document.addEventListener('visibilitychange', onVisible);
    // Faster while something is being processed
    const timer = setInterval(tick, fast ? 2000 : 5000);
    tick();
    return () => { document.removeEventListener('visibilitychange', onVisible); clearInterval(timer); };
  });
  // After an upload finishes the store resets version to null: reload now
  $effect(() => { if (authenticated && app.version === null) get('/sync').then((s) => { app.version = s.version; app.sync = s; }).catch(() => {}); });

  // Files: picker, drag and drop anywhere in the window, paste
  let picker = $state();
  const chooseFiles = () => picker.click();
  function picked(e) {
    const files = [...(e.currentTarget.files ?? [])];
    e.currentTarget.value = '';
    queueFiles(files);
  }
  function queueFiles(files) {
    if (!files.length) return;
    sendFiles(files);
    toast(t('upload.queued', { n: files.length }));
    if (page !== 'imports' && files.length > 3) location.hash = '#/imports';
  }
  let dragging = $state(0);
  const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
  $effect(() => {
    if (!authenticated) return;
    const enter = (e) => { if (hasFiles(e)) { e.preventDefault(); dragging++; } };
    const leave = (e) => { if (hasFiles(e)) dragging = Math.max(0, dragging - 1); };
    const over = (e) => { if (hasFiles(e)) e.preventDefault(); };
    const drop = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragging = 0;
      queueFiles([...e.dataTransfer.files]);
    };
    const paste = (e) => {
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      const files = [...(e.clipboardData?.files ?? [])];
      if (files.length) queueFiles(files);
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over);
    window.addEventListener('drop', drop);
    window.addEventListener('paste', paste);
    return () => {
      window.removeEventListener('dragenter', enter); window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', over); window.removeEventListener('drop', drop); window.removeEventListener('paste', paste);
    };
  });

  const importBadge = $derived(app.sync.errors + failedUploads() || app.sync.active + pendingUploads() || 0);
  const importBadgeErr = $derived(app.sync.errors + failedUploads() > 0);

  setUnauthorizedHandler(() => { if (app.me) app.me = { ...app.me, authenticated: false }; });

  async function start() {
    try {
      const me = await loadMe();
      if (me.authenticated && me.user.language) setLanguage(me.user.language);
      status = 'ready';
    } catch (e) { showError(e); status = 'error'; }
  }
  start();

  async function logout(alreadyDeleted = false) {
    if (pendingUploads() && !confirm(t('upload.leave_pending'))) return;
    if (!alreadyDeleted) await post('/logout').catch(() => {});
    uploads.items = [];
    await loadMe().catch(() => {});
    location.hash = '#/login';
  }
  async function resend() {
    try { await post('/account/resend-verification'); toast(t('account.verification_sent')); } catch (e) { showError(e); }
  }
</script>

{#if status === 'loading'}
  <main class="center"><img class="pulse" src="/icon.svg" alt={t('common.wait')} width="56" height="56" /></main>
{:else if status === 'error'}
  <main class="center"><p class="empty">{t('error.server')}<br /><button class="btn soft" onclick={start}>{t('common.retry')}</button></p></main>
{:else if !authenticated || ['verify', 'invite', 'privacy'].includes(page)}
  <div class="public-language"><LanguageSwitch /></div>
  {#if page === 'signup'}<Signup ondone={start} external={!!route.query.get('external')} />
  {:else if page === 'forgot-password'}<ForgotPassword />
  {:else if page === 'reset'}<ResetPassword token={route.param} ondone={start} />
  {:else if page === 'verify'}<VerifyEmail token={route.param} ondone={start} />
  {:else if page === 'invite'}<Invite token={route.param} ondone={start} />
  {:else if page === 'privacy'}<Privacy />
  {:else}<Login ondone={start} initialError={route.query.get('error') ?? ''} />{/if}
{:else}
  <div class="shell">
    <nav class="nav" aria-label={t('nav.sections')}>
      <a class="logo" href="#/archive"><img src="/icon.svg" alt="" width="28" height="28" /><span>paTrack</span></a>
      <div class="nav-apps hide-mobile"><AppSwitcher hub={app.me.hub} lang={language.id} label /></div>
      {#each NAV as id (id)}
        <a href="#/{id}" class:on={page === id} aria-current={page === id ? 'page' : undefined}>
          <span class="ico"><Icon name={id === 'family' ? 'family' : id} size={22} />
            {#if id === 'imports' && importBadge}<span class="count" class:err={importBadgeErr}>{importBadge}</span>{/if}</span>
          <span class="lbl">{t('nav.' + id)}</span>
        </a>
      {/each}
      <button class="scan-nav hide-desktop" onclick={() => (app.scanner = true)} aria-label={t('scan.title')}>
        <span class="ico"><Icon name="scan" size={22} /></span><span class="lbl">{t('scan.short')}</span>
      </button>
      <button class="logout hide-mobile" onclick={() => logout()} title={app.me.user.email}>
        <Icon name="logout" size={18} /><span class="lbl">{t('account.sign_out')}</span>
      </button>
    </nav>
    <main class="main">
      <!-- Phone: a slim top bar, so the other apps and signing out are always one tap away (as in doTrack/eaTrack) -->
      <div class="topbar hide-desktop">
        <a class="brand" href="#/archive"><img src="/icon.svg" alt="" width="24" height="24" /><span>paTrack</span></a>
        <AppSwitcher hub={app.me.hub} lang={language.id} />
        <span class="grow"></span>
        <button class="btn ghost sm" onclick={() => logout()} aria-label={t('account.sign_out')}>
          <Icon name="logout" size={16} /><span>{t('account.sign_out')}</span>
        </button>
      </div>
      {#if !app.online}
        <div class="notice small offline" role="status"><span>{t('offline.banner')}</span></div>
      {/if}
      {#if !app.me.user.email_verified}
        <div class="notice small">
          <span>{t('account.not_verified', { email: app.me.user.email })}</span>
          <button class="btn ghost sm" onclick={resend}>{t('account.resend')}</button>
        </div>
      {/if}
      {#key page + ':' + app.me.family?.id}
        {#if page === 'family'}
          <Family onlogout={logout} initialError={route.query.get('error') ?? ''} section={route.query.get('section') ?? ''} />
        {:else if page === 'tax'}
          <Tax />
        {:else if page === 'imports'}
          <Imports onupload={chooseFiles} onscan={() => (app.scanner = true)} />
        {:else}
          <Archive query={route.name === 'archive' ? route.query : new URLSearchParams()} onupload={chooseFiles} onscan={() => (app.scanner = true)} />
        {/if}
      {/key}
    </main>
  </div>
  <input bind:this={picker} type="file" multiple hidden onchange={picked} />
  {#if dragging}
    <div class="dropping" aria-hidden="true"><div><Icon name="imports" size={40} /><p>{t('upload.drop_here')}</p></div></div>
  {/if}
{/if}
{#if openDoc}{#key openDoc}<DocSheet id={openDoc} onclose={closeDoc} />{/key}{/if}
{#if app.scanner && authenticated}<Scanner onclose={() => (app.scanner = false)} />{/if}
<Toast />

<style>
  .nav-apps { margin: -10px 0 8px; }
  .center { min-height: 100dvh; display: grid; place-items: center; padding: 16px; }
  .pulse { border-radius: 12px; animation: pulse 1s ease-in-out infinite alternate; }
  @keyframes pulse { to { opacity: 0.5; } }
  .public-language { position: absolute; top: 12px; right: 12px; z-index: 5; }

  .main { padding: 20px 16px calc(var(--nav-h) + 96px + env(safe-area-inset-bottom)); max-width: 1100px; margin: 0 auto; }
  .notice.offline { background: var(--danger-soft); color: var(--danger); font-weight: 550; }
  .notice { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
    padding: 8px 12px; margin-bottom: 16px; border-radius: var(--r-sm); background: var(--primary-soft); }

  /* Phone: bottom bar */
  .nav {
    position: fixed; z-index: 50; left: 0; right: 0; bottom: 0;
    height: calc(var(--nav-h) + env(safe-area-inset-bottom)); padding: 6px 6px env(safe-area-inset-bottom);
    display: flex; background: var(--surface); border-top: 1px solid var(--line);
  }
  .logo { display: none; }
  .topbar { display: flex; align-items: center; gap: 4px; margin: -8px 0 12px; }
  .topbar .grow { flex: 1; }
  .topbar .btn { gap: 6px; }
  .brand { display: flex; align-items: center; gap: 8px; text-decoration: none; color: var(--ink); font-weight: 650; letter-spacing: -0.02em; }
  .brand img { border-radius: 6px; }
  .nav a:not(.logo), .scan-nav {
    flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
    text-decoration: none; color: var(--muted); font-weight: 500; font-size: 0.7rem; border-radius: var(--r-sm);
    -webkit-tap-highlight-color: transparent; border: 0; background: none; cursor: pointer; font-family: inherit;
  }
  .lbl { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ico { position: relative; width: 22px; height: 22px; display: grid; place-items: center; }
  .count { position: absolute; top: -6px; right: -12px; min-width: 17px; height: 17px; padding: 0 4px; border-radius: 9px;
    background: var(--primary); color: var(--primary-ink); font-size: 0.65rem; font-weight: 700; display: grid; place-items: center; }
  .count.err { background: var(--danger); color: #fff; }
  .nav a.on { color: var(--primary); }

  .dropping { position: fixed; inset: 0; z-index: 300; background: color-mix(in srgb, var(--primary) 18%, transparent);
    display: grid; place-items: center; pointer-events: none; }
  .dropping div { background: var(--surface); border: 2px dashed var(--primary); border-radius: var(--r-lg); padding: 30px 44px;
    display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--primary); font-weight: 600; }

  /* Desktop: sidebar */
  @media (min-width: 900px) {
    .shell { display: grid; grid-template-columns: 220px 1fr; }
    .nav { position: sticky; top: 0; height: 100dvh; flex-direction: column; gap: 2px; padding: 20px 12px; border-top: 0; border-right: 1px solid var(--line); }
    .logo { display: flex; align-items: center; gap: 10px; padding: 4px 10px 18px; text-decoration: none; color: var(--ink); font-size: 1.15rem; font-weight: 650; letter-spacing: -0.02em; }
    .logo img { border-radius: 7px; }
    .nav a:not(.logo) { flex: none; flex-direction: row; justify-content: flex-start; gap: 10px; padding: 9px 12px; font-size: 0.92rem; }
    .nav a:not(.logo) .ico { width: 18px; height: 18px; }
    .nav a:not(.logo) .ico :global(svg) { width: 18px; height: 18px; }
    .count { position: static; margin-left: 4px; }
    .nav a:not(.logo) .ico { display: flex; width: auto; }
    .nav a.on { background: var(--primary-soft); }
    .main { padding: 32px 32px 48px; width: 100%; max-width: 1680px; }
    .logout { margin-top: auto; display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 0; border-radius: var(--r-sm);
      background: transparent; color: var(--muted); font: inherit; font-weight: 500; font-size: 0.92rem; cursor: pointer; text-align: left; }
    .logout:hover { color: var(--ink); background: var(--surface-2); }
  }
</style>

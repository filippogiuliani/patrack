<script>
  import { del, get, post, put } from '../lib/api.js';
  import { app, loadMe, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { fmtDate } from '../lib/date.js';
  import LanguageSwitch from '../components/LanguageSwitch.svelte';
  import Icon from '../components/Icon.svelte';

  let { onlogout, initialError = '', section = '' } = $props();
  let family = $state(null);
  let invite = $state(null);
  let familyName = $state('');
  let userName = $state(app.me?.user?.name ?? '');
  let pwd = $state({ current: '', new: '' });

  const admin = $derived(family?.role === 'admin');
  const user = $derived(app.me?.user);
  const server = location.origin;

  async function load() {
    try { family = await get('/family'); familyName = family.name; } catch (e) { showError(e); }
  }
  $effect(() => { app.me?.family?.id; load(); });
  $effect(() => { if (initialError) toast(initialError, 'error'); });
  // #/family?section=import: jump to the ways of importing
  $effect(() => {
    if (family && section) setTimeout(() => document.getElementById('section-' + section)?.scrollIntoView({ behavior: 'smooth' }), 50);
  });

  async function run(fn, message) {
    try { await fn(); if (message) toast(message); await loadMe(); await load(); return true; } catch (e) { showError(e); return false; }
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast(t('common.copied')); } catch { /* stays visible */ }
  }
  const usedOn = (s) => fmtDate(s.slice(0, 10));

  // --- Family
  const rename = () => run(() => put('/family', { name: familyName }), t('common.saved'));
  const switchFamily = (id) => run(() => post('/family/switch', { family_id: id }));

  // --- People
  let newPerson = $state({ name: '', birth_date: '' });
  let editing = $state(null); // { id, name, birth_date }
  async function addPerson(e) {
    e.preventDefault();
    const name = newPerson.name.trim();
    if (name && await run(() => post('/family/people', { name, birth_date: newPerson.birth_date || null }), t('people.added', { name })))
      newPerson = { name: '', birth_date: '' };
  }
  async function savePerson(e) {
    e.preventDefault();
    if (await run(() => put(`/family/people/${editing.id}`, { name: editing.name, birth_date: editing.birth_date || null }), t('common.saved')))
      editing = null;
  }
  async function removePerson(p) {
    if (!confirm(t('people.confirm_delete', { name: p.name }))) return;
    await run(() => del(`/family/people/${p.id}`));
  }

  // --- Members and invitations
  async function createInvite() {
    try { invite = await post('/family/invites'); } catch (e) { showError(e); }
  }
  async function shareInvite() {
    const text = t('invite.message', { family: family.name });
    if (navigator.share) {
      try { await navigator.share({ title: 'paTrack', text, url: invite.link }); return; } catch { /* cancelled */ }
    }
    copy(invite.link);
  }
  async function remove(m) {
    const self = m.me;
    if (!confirm(self ? t('family.confirm_leave') : t('family.confirm_remove', { name: m.name }))) return;
    await run(() => del(`/family/members/${m.id}`), self ? t('family.left') : t('family.removed'));
  }

  // --- iPhone Shortcut (API token)
  let tokens = $state([]);
  let newToken = $state(null);
  $effect(() => { app.me?.family?.id; get('/account/tokens').then((d) => (tokens = d)).catch(() => {}); });
  async function createToken() {
    try { newToken = await post('/account/tokens', { name: t('iphone.token_name') }); tokens = await get('/account/tokens'); } catch (e) { showError(e); }
  }
  async function revokeToken(tk) {
    if (!confirm(t('api.confirm_revoke', { name: tk.name }))) return;
    try { tokens = await del(`/account/tokens/${tk.id}`); } catch (e) { showError(e); }
  }

  // --- Email import: addresses I forward from
  let newSender = $state('');
  async function addSender(e) {
    e.preventDefault();
    if (await run(() => post('/account/mail-senders', { email: newSender.trim() }), t('common.saved'))) newSender = '';
  }
  const removeSender = (s) => run(() => del(`/account/mail-senders/${encodeURIComponent(s)}`));

  // --- Backup
  const offsiteAge = $derived(family?.backup?.offsite?.at ? (Date.now() - new Date(family.backup.offsite.at)) / 86400000 : null);
  const offsiteWarn = $derived(!family?.backup?.offsite || family.backup.offsite.ok === false || offsiteAge > 2);
  const fmtWhen = (s) => new Date(s).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  // --- Two-step verification
  let twofa = $state(null);
  let setup = $state(null);
  let setupCode = $state('');
  let recovery = $state(null);
  $effect(() => { get('/account/2fa').then((d) => (twofa = d)).catch(() => {}); });
  async function startSetup() {
    try { setup = await post('/account/2fa/setup'); setupCode = ''; } catch (e) { showError(e); }
  }
  async function confirmSetup(e) {
    e.preventDefault();
    try {
      const r = await post('/account/2fa/enable', { code: setupCode });
      twofa = r; recovery = r.recovery_codes; setup = null;
      toast(t('twofa.enabled')); await loadMe();
    } catch (err) { showError(err); }
  }
  function confirmation() {
    const v = prompt(user.has_password ? t('twofa.confirm_password_or_code') : t('twofa.confirm_code'))?.trim();
    if (!v) return null;
    return /^\d{6}$/.test(v.replace(/\s/g, '')) || /^[0-9a-f]{4}-?[0-9a-f]{4}$/i.test(v) ? { code: v } : { password: v };
  }
  async function disable2fa() {
    const c = confirmation();
    if (!c) return;
    try { twofa = await post('/account/2fa/disable', c); recovery = null; toast(t('twofa.disabled')); await loadMe(); } catch (e) { showError(e); }
  }
  async function newCodes() {
    const c = confirmation();
    if (!c) return;
    try { const r = await post('/account/2fa/recovery-codes', c); twofa = r; recovery = r.recovery_codes; } catch (e) { showError(e); }
  }
  async function signOutElsewhere() {
    if (!confirm(t('security.confirm_others'))) return;
    try { await post('/account/sessions/revoke'); toast(t('security.others_out')); } catch (e) { showError(e); }
  }

  // --- Account
  const saveName = () => run(() => put('/account', { name: userName }), t('common.saved'));
  const saveLanguage = (l) => run(() => put('/account', { language: l }));
  async function changePassword(e) {
    e.preventDefault();
    if (await run(() => post('/account/password', pwd), t('account.password_changed'))) pwd = { current: '', new: '' };
  }
  const unlink = (p) => run(() => del(`/account/identities/${p}`), t('account.unlinked'));
  async function deleteAccount() {
    const answer = user.has_password ? prompt(t('account.delete_password')) : prompt(t('account.delete_email', { email: user.email }));
    if (!answer) return;
    try {
      await del('/account', user.has_password ? { password: answer } : { confirm_email: answer });
      toast(t('account.deleted'));
      onlogout(true);
    } catch (e) { showError(e); }
  }
</script>

<header class="head"><h1>{t('nav.family')}</h1><p class="muted">{t('family.subtitle')}</p></header>

{#if family && user}
<div class="layout">
  {#if app.me.hub}
  <!-- Managed in weHub -->
  <section class="card stack">
    <h2>{t('family.family')}</h2>
    <p><b>{family.name}</b></p>
    <p class="small muted">{t('hub.managed')}</p>
    <ul class="list">
      {#each family.members as m (m.id)}
        <li><div class="grow"><b>{m.name}</b>{#if m.me}<span class="muted small you">({t('family.you')})</span>{/if}
          <div class="tiny muted">{m.email} · {m.role === 'admin' ? t('family.role_admin') : t('family.role_member')}</div></div></li>
      {/each}
    </ul>
    <p class="small">{t('people.title')}: {family.people.map((p) => p.name).join(', ')}</p>
    <a class="btn primary" href="{app.me.hub.url}/#/family">{t('hub.open')}</a>
  </section>
  {:else}
  <!-- Family -->
  <section class="card stack">
    <h2>{t('family.family')}</h2>
    {#if admin}
      <form class="row" onsubmit={(e) => { e.preventDefault(); rename(); }}>
        <input class="input grow" bind:value={familyName} maxlength="80" aria-label={t('family.name')} />
        <button class="btn" disabled={!familyName.trim() || familyName === family.name}>{t('common.save')}</button>
      </form>
    {:else}
      <p><b>{family.name}</b></p>
    {/if}
    {#if app.me.families.length > 1}
      <div class="seg">
        {#each app.me.families as f (f.id)}
          <button class:on={f.id === app.me.family.id} onclick={() => switchFamily(f.id)}>{f.name}</button>
        {/each}
      </div>
    {/if}
    <h3 class="sub">{t('family.members')}</h3>
    <ul class="list">
      {#each family.members as m (m.id)}
        <li>
          <div class="grow">
            <b>{m.name}</b>{#if m.me}<span class="muted small you">({t('family.you')})</span>{/if}
            <div class="tiny muted email">{m.email} · {m.role === 'admin' ? t('family.role_admin') : t('family.role_member')}</div>
          </div>
          {#if m.me && family.members.length > 1}
            <button class="btn ghost sm" onclick={() => remove(m)}>{t('family.leave')}</button>
          {:else if admin && !m.me}
            <button class="btn ghost sm" onclick={() => remove(m)}>{t('family.remove')}</button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if admin}
      {#if invite}
        <div class="invite stack">
          <p class="small">{t('invite.instructions')}</p>
          <input class="input" readonly value={invite.link} onfocus={(e) => e.currentTarget.select()} aria-label={t('invite.link')} />
          <button class="btn primary" onclick={shareInvite}>{t('invite.share')}</button>
        </div>
      {:else}
        <button class="btn primary" onclick={createInvite}>{t('invite.create')}</button>
        <p class="tiny muted">{t('invite.explanation')}</p>
      {/if}
    {/if}
  </section>

  <!-- People -->
  <section class="card stack">
    <h2 class="ic"><Icon name="people" />{t('people.title')}</h2>
    <p class="small muted">{t('people.explain')}</p>
    <ul class="list">
      {#each family.people as p (p.id)}
        <li>
          {#if editing?.id === p.id}
            <form class="row wrap grow" onsubmit={savePerson}>
              {#if !p.user_id}<input class="input grow" bind:value={editing.name} maxlength="60" aria-label={t('common.name')} />{/if}
              <input class="input date" type="date" bind:value={editing.birth_date} aria-label={t('people.birth_date')} />
              <button class="btn sm primary">{t('common.save')}</button>
              <button type="button" class="btn sm ghost" onclick={() => (editing = null)}>{t('common.cancel')}</button>
            </form>
          {:else}
            <div class="grow">
              <span class="name">{p.name}</span>
              <div class="tiny muted">{p.user_id ? t('people.member') : t('people.no_account')}{#if p.birth_date} · {t('people.born', { date: fmtDate(p.birth_date) })}{/if}</div>
            </div>
            <button class="btn icon sm ghost" onclick={() => (editing = { id: p.id, name: p.name, birth_date: p.birth_date ?? '' })}
                    aria-label={t('people.edit', { name: p.name })}><Icon name="edit" size={16} /></button>
            {#if !p.user_id}
              <button class="btn icon sm ghost" onclick={() => removePerson(p)} aria-label={t('people.delete', { name: p.name })}><Icon name="trash" size={16} /></button>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>
    <form class="row wrap" onsubmit={addPerson}>
      <input class="input grow" bind:value={newPerson.name} maxlength="60" placeholder={t('people.placeholder')} aria-label={t('people.placeholder')} />
      <input class="input date" type="date" bind:value={newPerson.birth_date} aria-label={t('people.birth_date')} title={t('people.birth_date')} />
      <button class="btn" disabled={!newPerson.name.trim()}>{t('people.add')}</button>
    </form>
  </section>

  {/if}

  <!-- iPhone -->
  <section class="card stack" id="section-import">
    <h2 class="ic"><Icon name="phone" />{t('iphone.title')}</h2>
    <p class="small">{t('iphone.intro')}</p>
    {#if newToken}
      <div class="invite stack">
        <span class="label">{t('iphone.your_token')}</span>
        <div class="row"><input class="input grow mono" readonly value={newToken.token} onfocus={(e) => e.currentTarget.select()} aria-label={t('iphone.your_token')} />
          <button class="btn icon soft" onclick={() => copy(newToken.token)} aria-label={t('common.copy')}><Icon name="copy" /></button></div>
        <p class="tiny">{t('iphone.token_once')}</p>
      </div>
    {:else}
      <button class="btn primary" onclick={createToken}><Icon name="key" size={16} />{t('iphone.create_token')}</button>
    {/if}
    <details open={!!newToken}>
      <summary>{t('iphone.how')}</summary>
      <ol class="how small">
        <li>{t('iphone.step1')}</li>
        <li>{t('iphone.step2')}</li>
        <li>{t('iphone.step3')}</li>
        <li>{t('iphone.step4')}
          <div class="creds">
            <div class="row"><span class="tiny muted k">URL</span><code class="mono grow url">{server}/api/imports</code>
              <button class="btn icon sm ghost" onclick={() => copy(server + '/api/imports')} aria-label={t('common.copy')}><Icon name="copy" size={15} /></button></div>
            <div class="row"><span class="tiny muted k">{t('iphone.method')}</span><code class="mono grow">POST</code></div>
            <div class="row"><span class="tiny muted k">{t('iphone.header')}</span><code class="mono grow url">Authorization: Bearer {newToken ? newToken.token : 'pt_…'}</code>
              {#if newToken}<button class="btn icon sm ghost" onclick={() => copy('Bearer ' + newToken.token)} aria-label={t('common.copy')}><Icon name="copy" size={15} /></button>{/if}</div>
            <div class="row"><span class="tiny muted k">{t('iphone.body')}</span><code class="mono grow">{t('iphone.body_value')}</code></div>
          </div>
        </li>
        <li>{t('iphone.step5')}</li>
        <li>{t('iphone.step6')}</li>
      </ol>
      <p class="tiny muted">{t('iphone.scan_tip')}</p>
    </details>
    {#if tokens.length}
      <h3 class="sub">{t('iphone.tokens')}</h3>
      <ul class="list">
        {#each tokens as tk (tk.id)}
          <li>
            <div class="grow"><b>{tk.name}</b> <span class="tiny muted mono">{tk.hint}</span>
              <div class="tiny muted">{tk.last_used_at ? t('api.last_used', { date: usedOn(tk.last_used_at) }) : t('api.never_used')}</div></div>
            <button class="btn ghost sm" onclick={() => revokeToken(tk)}>{t('api.revoke')}</button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- Email -->
  <section class="card stack">
    <h2 class="ic"><Icon name="mail" />{t('mail.title')}</h2>
    {#if family.inbox.address}
      <p class="small">{t('mail.intro')}</p>
      <div class="row"><code class="mono grow url big">{family.inbox.address}</code>
        <button class="btn icon soft" onclick={() => copy(family.inbox.address)} aria-label={t('common.copy')}><Icon name="copy" /></button></div>
      {#if !family.inbox.enabled}
        <p class="small warn">{t('mail.not_configured')}</p>
      {:else if family.inbox.last_error}
        <p class="small warn ic"><Icon name="alert" size={14} />{t('mail.error', { error: family.inbox.last_error })}</p>
      {:else if family.inbox.last_ok}
        <p class="tiny muted">{t('mail.last_check', { date: fmtWhen(family.inbox.last_ok) })}</p>
      {/if}
    {:else}
      <p class="small muted">{admin ? t('mail.off_admin') : t('mail.off')}</p>
    {/if}
    <h3 class="sub">{t('mail.senders')}</h3>
    <p class="tiny muted">{t('mail.senders_explain')}</p>
    <ul class="list">
      <li><span class="grow email">{user.email}</span><span class="tiny muted">{t('mail.account_email')}</span></li>
      {#each family.mail_senders as s (s)}
        <li><span class="grow email">{s}</span>
          <button class="btn icon sm ghost" onclick={() => removeSender(s)} aria-label={t('common.remove')}><Icon name="trash" size={15} /></button></li>
      {/each}
    </ul>
    <form class="row" onsubmit={addSender}>
      <input class="input grow" type="email" bind:value={newSender} placeholder={t('mail.add_placeholder')} aria-label={t('mail.add_placeholder')} />
      <button class="btn" disabled={!newSender.includes('@')}>{t('people.add')}</button>
    </form>
  </section>

  <!-- Backup -->
  <section class="card stack">
    <h2 class="ic"><Icon name="shield" />{t('backup.title')}</h2>
    <ul class="list">
      <li><span class="grow">{t('backup.local')}</span>
        <span class="small">{family.backup.last_local ? fmtWhen(family.backup.last_local) : t('backup.never')}</span></li>
      <li><span class="grow">{t('backup.offsite')}</span>
        <span class="small" class:warn={offsiteWarn}>
          {#if family.backup.offsite}
            {family.backup.offsite.ok === false ? t('backup.failed') + ' · ' : ''}{fmtWhen(family.backup.offsite.at)}
          {:else}{t('backup.never')}{/if}
        </span></li>
    </ul>
    {#if family.backup.offsite?.ok === false && family.backup.offsite.message}<p class="tiny warn">{family.backup.offsite.message}</p>{/if}
    {#if offsiteWarn}<p class="small warn ic top"><Icon name="alert" size={14} />{t('backup.warn')}</p>{/if}
    <p class="tiny muted">{t('backup.explain')}</p>
  </section>

  <!-- Account -->
  <section class="card stack">
    <h2>{t('account.title')}</h2>
    <form class="row" onsubmit={(e) => { e.preventDefault(); saveName(); }}>
      <input class="input grow" bind:value={userName} maxlength="80" aria-label={t('auth.your_name')} />
      <button class="btn" disabled={!userName.trim() || userName === user.name}>{t('common.save')}</button>
    </form>
    <div class="spread wrap">
      <span class="small email">{user.email}</span>
      {#if user.email_verified}<span class="badge ok">{t('account.verified')}</span>{/if}
    </div>
    <div class="spread">
      <span class="small">{t('common.language')}</span>
      <LanguageSwitch onchoose={saveLanguage} />
    </div>

    {#if !app.me.hub && (app.me.password_login || user.has_password)}
      <h3 class="sub">{user.has_password ? t('account.change_password') : t('account.set_password')}</h3>
      <form class="stack" onsubmit={changePassword}>
        {#if user.has_password}
          <input class="input" type="password" bind:value={pwd.current} placeholder={t('account.current_password')} autocomplete="current-password" required />
        {/if}
        <input class="input" type="password" bind:value={pwd.new} placeholder={t('auth.new_password')} autocomplete="new-password" minlength="8" required />
        <button class="btn">{t('auth.save_password')}</button>
      </form>

      <h3 class="sub ic"><Icon name="key" size={16} />{t('twofa.title')}</h3>
      {#if twofa}
        {#if twofa.enabled}
          <p class="small"><span class="badge ok"><Icon name="check" size={12} />{t('twofa.on')}</span>
            <span class="tiny muted">{t('twofa.codes_left', { n: twofa.recovery_left })}</span></p>
          <div class="row wrap">
            <button class="btn sm" onclick={newCodes}>{t('twofa.new_codes')}</button>
            <button class="btn ghost sm" onclick={disable2fa}>{t('twofa.disable')}</button>
          </div>
        {:else if setup}
          <div class="invite stack">
            <p class="small">{t('twofa.scan')}</p>
            <img class="qr" src={setup.qr} alt={t('twofa.qr_alt')} width="200" height="200" />
            <p class="tiny">{t('twofa.or_type')} <code class="mono">{setup.secret}</code>
              <a class="hide-desktop" href={setup.uri}>{t('twofa.open_app')}</a></p>
            <form class="row" onsubmit={confirmSetup}>
              <input class="input grow mono" bind:value={setupCode} inputmode="numeric" autocomplete="one-time-code" maxlength="6"
                     placeholder="123456" aria-label={t('twofa.code')} />
              <button class="btn primary" disabled={setupCode.replace(/\D/g, '').length !== 6}>{t('twofa.confirm')}</button>
            </form>
            <button class="btn ghost sm" onclick={() => (setup = null)}>{t('common.close')}</button>
          </div>
        {:else}
          <p class="small muted">{t('twofa.explain')}</p>
          <button class="btn" onclick={startSetup}>{t('twofa.enable')}</button>
        {/if}
        {#if recovery}
          <div class="invite stack">
            <p class="small"><b>{t('twofa.recovery_title')}</b> {t('twofa.recovery_explain')}</p>
            <pre class="codes mono">{recovery.join('\n')}</pre>
            <button class="btn soft sm" onclick={() => copy(recovery.join('\n'))}><Icon name="copy" size={15} />{t('common.copy')}</button>
          </div>
        {/if}
      {/if}
    {/if}
    <button class="btn ghost sm others" onclick={signOutElsewhere}>{t('security.sign_out_others')}</button>

    {#if app.me.oidc?.length && !app.me.hub}
      <h3 class="sub">{t('account.sign_ins')}</h3>
      <ul class="list">
        {#each app.me.oidc as p (p.id)}
          <li>
            <span class="grow">{p.name}</span>
            {#if user.identities.includes(p.id)}
              <span class="badge ok">{t('account.linked')}</span>
              <button class="btn ghost sm" onclick={() => unlink(p.id)}>{t('account.unlink')}</button>
            {:else}
              <a class="btn ghost sm" href="/api/oidc/{encodeURIComponent(p.id)}/login?link=1">{t('account.link')}</a>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    <div class="row wrap sub">
      <button class="btn" onclick={() => onlogout()}>{t('account.sign_out')}</button>
      {#if !app.me.hub}<button class="btn danger" onclick={deleteAccount}>{t('account.delete')}</button>{/if}
    </div>
    <p class="tiny muted">{#if !app.me.hub}{t('account.delete_note')} {/if}<a href="#/privacy">{t('auth.privacy_notice')}</a></p>
  </section>
</div>
{/if}

<style>
  .head { margin-bottom: 18px; }
  .layout { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr); }
  .layout > .card { min-width: 0; }
  @media (min-width: 1000px) { .layout { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; } }
  .email { overflow-wrap: anywhere; }
  .name { font-weight: 600; overflow-wrap: anywhere; }
  .sub { margin-top: 8px; }
  .list { list-style: none; margin: 0; padding: 0; }
  .list li { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .list li:last-child { border: 0; }
  .list b { font-weight: 600; }
  .you { margin-left: 4px; }
  .invite { padding: 12px; border-radius: var(--r-md); background: var(--primary-soft); }
  .ic { display: flex; align-items: center; gap: 8px; }
  .ic.top { align-items: flex-start; }
  .ic.top :global(svg) { margin-top: 3px; }
  .date { width: auto; min-width: 150px; }
  details summary { cursor: pointer; color: var(--primary); font-weight: 500; }
  .how { margin: 10px 0 8px; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; }
  .creds { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; padding: 8px 10px; background: var(--surface-2); border-radius: var(--r-sm); }
  .creds .k { width: 82px; flex-shrink: 0; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem; }
  .url { overflow-wrap: anywhere; }
  .big { font-size: 0.95rem; padding: 8px 10px; background: var(--surface-2); border-radius: var(--r-sm); }
  .warn { color: var(--danger); }
  .qr { align-self: center; border-radius: var(--r-sm); background: #fff; padding: 4px; }
  .codes { margin: 0; padding: 10px; background: var(--surface); border-radius: var(--r-sm); columns: 2; font-size: 0.9rem; }
  .others { align-self: flex-start; }
</style>

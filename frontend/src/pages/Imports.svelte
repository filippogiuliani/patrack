<script>
  // The import queue: files still leaving this device, then what the server did with each one.
  // Nothing disappears on its own: errors stay until retried or dismissed.
  import { get, post } from '../lib/api.js';
  import { app, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { fmtSize, reasonText } from '../lib/docs.js';
  import { forgetUpload, retryAllUploads, retryUpload, uploads } from '../lib/uploads.svelte.js';
  import Icon from '../components/Icon.svelte';

  let { onupload, onscan } = $props();
  let queue = $state(null);

  async function load() {
    try { queue = await get('/imports'); } catch (e) { showError(e); }
  }
  $effect(() => { app.version; load(); });

  const counts = $derived(queue?.counts ?? {});
  const failedLocal = $derived(uploads.items.filter((u) => u.state === 'failed').length);

  async function act(fn, message) {
    try { await fn(); if (message) toast(message); await load(); } catch (e) { showError(e); }
  }
  const retry = (i) => act(() => post(`/imports/${i.id}/retry`));
  const retryAll = () => act(() => post('/imports/retry-all'), t('imports.retrying'));
  const keep = (i) => act(() => post(`/imports/${i.id}/keep`), t('imports.kept'));
  const dismiss = (i) => act(() => post(`/imports/${i.id}/dismiss`));
  const clearDone = () => act(() => post('/imports/dismiss-done'));

  const SOURCE_ICON = { upload: 'upload', scan: 'scan', shortcut: 'phone', email: 'mail', api: 'refresh' };
  function when(s) {
    const d = new Date(s.replace(' ', 'T') + 'Z');
    return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
  // Drag and drop on the drop area (the whole window accepts files too, see App)
  let over = $state(false);
</script>

<header class="head">
  <h1>{t('nav.imports')}</h1>
  <p class="muted">{t('imports.subtitle')}</p>
</header>

<div class="drop" class:over role="region" aria-label={t('imports.drop')}
     ondragover={(e) => { e.preventDefault(); over = true; }} ondragleave={() => (over = false)} ondrop={() => (over = false)}>
  <Icon name="imports" size={30} />
  <p><b>{t('imports.drop')}</b></p>
  <div class="row wrap center">
    <button class="btn primary" onclick={onupload}><Icon name="upload" size={17} />{t('upload.choose')}</button>
    <button class="btn" onclick={onscan}><Icon name="scan" size={17} />{t('scan.short')}</button>
  </div>
  <p class="tiny muted">{t('imports.other_ways')} <a href="#/family?section=import">{t('imports.setup')}</a></p>
</div>

{#if uploads.items.length}
  <section class="block">
    <div class="spread"><h2>{t('imports.sending')}</h2>
      {#if failedLocal}<button class="btn sm" onclick={retryAllUploads}><Icon name="refresh" size={14} />{t('imports.retry_all', { n: failedLocal })}</button>{/if}</div>
    <ul class="rows">
      {#each uploads.items as u (u.key)}
        <li>
          <span class="st" class:err={u.state === 'failed'}><Icon name={u.state === 'failed' ? 'alert' : u.state === 'sent' ? 'check' : 'upload'} size={18} /></span>
          <div class="grow">
            <div class="name">{u.name}</div>
            {#if u.state === 'failed'}
              <div class="small err">{t('imports.not_sent')}: {u.error}</div>
            {:else if u.state === 'uploading'}
              <div class="bar"><span style="width: {Math.round(u.progress * 100)}%"></span></div>
            {:else}
              <div class="tiny muted">{u.state === 'sent' ? t('imports.received') : t('imports.waiting')} · {fmtSize(u.size)}</div>
            {/if}
          </div>
          {#if u.state === 'failed'}
            <button class="btn sm" onclick={() => retryUpload(u)}>{t('common.retry')}</button>
            <button class="btn icon sm ghost" onclick={() => forgetUpload(u)} aria-label={t('common.remove')}><Icon name="close" size={15} /></button>
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/if}

<section class="block">
  <div class="spread wrap">
    <h2>{t('imports.queue')}</h2>
    <div class="row wrap">
      {#if counts.error}<button class="btn sm" onclick={retryAll}><Icon name="refresh" size={14} />{t('imports.retry_all', { n: counts.error })}</button>{/if}
      {#if counts.done || counts.duplicate}<button class="btn ghost sm" onclick={clearDone}>{t('imports.clear_done')}</button>{/if}
    </div>
  </div>
  {#if queue && !queue.items.length}
    <p class="empty small">{t('imports.empty')}</p>
  {:else if queue}
    <ul class="rows">
      {#each queue.items as i (i.id)}
        <li class:fail={i.status === 'error'}>
          <span class="st" class:err={i.status === 'error'} title={t('source.' + i.source)}>
            <Icon name={i.status === 'error' ? 'alert' : i.status === 'done' ? 'check' : i.status === 'duplicate' ? 'copy' : 'refresh'} size={18} />
          </span>
          <div class="grow">
            <div class="name">
              {#if i.document_id && i.status !== 'error'}<a href="#/doc/{i.document_id}">{i.document_title ?? i.file_name}</a>{:else}{i.file_name}{/if}
            </div>
            <div class="small">
              {#if i.status === 'queued'}<span class="muted">{t('imports.queued')}</span>
              {:else if i.status === 'processing'}<span class="muted">{t('imports.processing')}</span>
              {:else if i.status === 'done'}
                {#if i.document_status === 'review'}<span>{t('imports.done_to_fix')}: {reasonText(i.review_reason)}</span>
                {:else}<span class="muted">{t('imports.done')}</span>{/if}
              {:else if i.status === 'duplicate'}
                <span>{t('imports.duplicate_of')} <a href="#/doc/{i.duplicate_of}">{i.duplicate_title}</a>{#if i.duplicate_deleted} ({t('imports.in_trash')}){/if}</span>
              {:else}
                <span class="err">{t('imports.error')}: {reasonText(i.error)}</span>
                {#if i.document_id}<span class="muted"> · {t('imports.saved_anyway')}</span>{/if}
              {/if}
            </div>
            <div class="tiny muted src">
              <Icon name={SOURCE_ICON[i.source] ?? 'upload'} size={12} />
              {t('source.' + i.source)}{#if i.email_from} · {i.email_from}{/if}{#if i.email_subject} · «{i.email_subject}»{/if}
              · {i.user_name ?? ''} · {when(i.created_at)}{#if i.attempts > 1} · {t('imports.attempts', { n: i.attempts })}{/if}
            </div>
            {#if i.status === 'error' && i.error_detail}<details class="tiny muted"><summary>{t('imports.details')}</summary>{i.error_detail}</details>{/if}
          </div>
          <div class="acts">
            {#if i.status === 'error' && i.document_id}<button class="btn sm" onclick={() => retry(i)}>{t('common.retry')}</button>{/if}
            {#if i.status === 'duplicate'}<button class="btn sm ghost" onclick={() => keep(i)}>{t('imports.keep')}</button>{/if}
            {#if !['queued', 'processing'].includes(i.status)}
              <button class="btn icon sm ghost" onclick={() => dismiss(i)} aria-label={t('imports.dismiss')} title={t('imports.dismiss')}><Icon name="close" size={15} /></button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted small">{t('common.wait')}</p>
  {/if}
</section>


<style>
  .head { margin-bottom: 16px; }
  .drop { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 26px 16px; text-align: center;
    border: 1.5px dashed var(--line-strong); border-radius: var(--r-lg); background: var(--surface); color: var(--muted); }
  .drop p b { color: var(--ink); font-weight: 600; }
  .drop.over { border-color: var(--primary); background: var(--primary-soft); }
  .center { justify-content: center; }
  .block { margin-top: 22px; display: flex; flex-direction: column; gap: 10px; }
  .rows { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); }
  .rows li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 4px 12px; padding: 12px 14px; }
  @media (max-width: 600px) {
    .rows li:has(.acts .btn:not(.icon)) .acts { grid-column: 2 / 4; grid-row: 2; justify-content: flex-start; }
  }
  .rows li + li { border-top: 1px solid var(--line); }
  .st { color: var(--muted); padding-top: 2px; }
  .err { color: var(--danger); }
  .name { font-weight: 600; overflow-wrap: anywhere; }
  .name a { color: inherit; }
  .src { margin-top: 2px; }
  .src :global(svg) { display: inline-block; vertical-align: -1px; margin-right: 2px; }
  .acts { display: flex; gap: 4px; align-items: center; flex-shrink: 0; }
  .bar { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; margin-top: 6px; }
  .bar span { display: block; height: 100%; background: var(--primary); transition: width 0.2s; }
  details summary { cursor: pointer; }
  details { overflow-wrap: anywhere; }
</style>

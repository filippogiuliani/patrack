<script>
  // The archive: free-text search, filters (kept in the address, so "back" and links work) and the documents found.
  import { untrack } from 'svelte';
  import { get } from '../lib/api.js';
  import { app, loadFacets, personName, showError } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { CATEGORIES, categoryName, expiryInfo, fmtAmount, reasonText, snippetHtml } from '../lib/docs.js';
  import { fmtDate } from '../lib/date.js';
  import Icon from '../components/Icon.svelte';

  let { query, onupload, onscan } = $props();

  const KEYS = ['q', 'person', 'category', 'year', 'expiry', 'status', 'sort', 'trash'];
  let f = $state(Object.fromEntries(KEYS.map((k) => [k, query.get(k) ?? ''])));
  let qInput = $state(f.q);
  let items = $state([]);
  let total = $state(0);
  let loading = $state(true);
  let more = $state(false);

  const filtered = $derived(KEYS.some((k) => k !== 'sort' && f[k]));
  const facets = $derived(app.facets);

  function params(offset = 0) {
    const p = new URLSearchParams();
    for (const k of KEYS) if (f[k]) p.set(k, f[k]);
    if (offset) p.set('offset', offset);
    return p;
  }
  // The filters live in the address: #/archive?q=…&person=…
  function writeHash() {
    const p = params().toString();
    history.replaceState(null, '', '#/archive' + (p ? '?' + p : ''));
  }

  let seq = 0;
  async function load(append = false) {
    const mine = ++seq;
    loading = !append;
    try {
      const r = await get('/documents?' + params(append ? items.length : 0));
      if (mine !== seq) return;
      items = append ? [...items, ...r.items] : r.items;
      total = r.total;
      more = items.length < r.total;
    } catch (e) { if (mine === seq) showError(e); } finally { if (mine === seq) loading = false; }
  }

  // Reload when filters change, and when something changed in the family (another upload finished, the partner edited…)
  $effect(() => {
    KEYS.forEach((k) => f[k]);
    untrack(() => { writeHash(); load(); });
  });
  $effect(() => { app.version; untrack(() => { loadFacets(); if (seq) load(); }); });

  // Typing: search after a short pause
  let timer;
  function typed() {
    clearTimeout(timer);
    timer = setTimeout(() => (f.q = qInput.trim()), 280);
  }
  function clearAll() {
    for (const k of KEYS) if (k !== 'sort') f[k] = '';
    qInput = '';
  }
  const set = (k, v) => () => (f[k] = f[k] === v ? '' : v);
  const thumb = (d) => `/api/documents/${d.id}/preview?v=${encodeURIComponent(d.updated_at)}`;
</script>

<header class="head">
  <div class="spread">
    <h1>{f.trash ? t('archive.trash') : t('nav.archive')}</h1>
    {#if !f.trash}
      <div class="row">
        <button class="btn soft hide-mobile" onclick={onscan}><Icon name="scan" size={17} />{t('scan.short')}</button>
        <button class="btn primary" onclick={onupload}><Icon name="upload" size={17} /><span>{t('upload.add')}</span></button>
      </div>
    {:else}
      <button class="btn ghost sm" onclick={() => (f.trash = '')}><Icon name="left" size={15} />{t('archive.back')}</button>
    {/if}
  </div>
  <div class="search searchbox">
    <input class="input" type="search" bind:value={qInput} oninput={typed} placeholder={t('archive.search')}
           aria-label={t('archive.search')} enterkeyhint="search" />
  </div>
</header>

<!-- Filters -->
<div class="filters">
  <div class="chips scroll">
    {#if facets?.review}
      <button class="chip" class:on={f.status === 'review'} onclick={set('status', 'review')}>
        <Icon name="alert" size={14} />{t('archive.to_fix')} <span class="q">{facets.review}</span></button>
    {/if}
    {#if facets?.soon || facets?.expired}
      <button class="chip" class:on={f.expiry === 'soon'} onclick={set('expiry', 'soon')}>{t('archive.expiring')} <span class="q">{facets.soon}</span></button>
      {#if facets.expired}<button class="chip" class:on={f.expiry === 'expired'} onclick={set('expiry', 'expired')}>{t('archive.expired')} <span class="q">{facets.expired}</span></button>{/if}
    {/if}
    {#each app.me.people as p (p.id)}
      <button class="chip" class:on={f.person === String(p.id)} onclick={set('person', String(p.id))}>{p.name}</button>
    {/each}
    <button class="chip" class:on={f.person === 'family'} onclick={set('person', 'family')}>{t('doc.whole_family')}</button>
  </div>
  <div class="selects">
    <select class="input" bind:value={f.category} aria-label={t('doc.category')}>
      <option value="">{t('archive.all_categories')}</option>
      {#each CATEGORIES as c}<option value={c}>{categoryName(c)}{facets?.categories?.[c] ? ` (${facets.categories[c]})` : ''}</option>{/each}
      {#if facets?.categories?.none}<option value="none">{t('cat.none')} ({facets.categories.none})</option>{/if}
    </select>
    <select class="input" bind:value={f.year} aria-label={t('archive.year')}>
      <option value="">{t('archive.all_years')}</option>
      {#each facets?.years ?? [] as y}<option value={y}>{y}</option>{/each}
    </select>
    <select class="input" bind:value={f.expiry} aria-label={t('doc.expiry')}>
      <option value="">{t('archive.any_expiry')}</option>
      <option value="soon">{t('archive.expiring')}</option>
      <option value="expired">{t('archive.expired')}</option>
      <option value="any">{t('archive.with_expiry')}</option>
    </select>
    <select class="input" bind:value={f.sort} aria-label={t('archive.sort')}>
      <option value="">{t('archive.sort_date')}</option>
      <option value="added">{t('archive.sort_added')}</option>
      <option value="expiry">{t('archive.sort_expiry')}</option>
      <option value="title">{t('archive.sort_title')}</option>
    </select>
  </div>
</div>

<div class="spread status-line">
  <span class="small muted">{loading ? t('common.wait') : t(total === 1 ? 'archive.one' : 'archive.n', { n: total })}</span>
  {#if filtered && !f.trash}<button class="btn ghost sm" onclick={clearAll}>{t('archive.clear')}</button>{/if}
</div>

{#if !loading && !items.length}
  <div class="empty">
    {#if f.trash}{t('archive.trash_empty')}
    {:else if filtered}{t('archive.nothing_found')}
    {:else}
      <p>{t('archive.empty')}</p>
      <div class="row center wrap first">
        <button class="btn primary" onclick={onupload}><Icon name="upload" size={17} />{t('upload.add')}</button>
        <button class="btn" onclick={onscan}><Icon name="scan" size={17} />{t('scan.short')}</button>
        <a class="btn ghost" href="#/family?section=import">{t('archive.other_ways')}</a>
      </div>
    {/if}
  </div>
{:else}
  <ul class="docs">
    {#each items as d (d.id)}
      {@const exp = expiryInfo(d.expiry_date)}
      <li>
        <a class="doc" href="#/doc/{d.id}">
          <span class="thumb">
            {#if d.has_preview}<img src={thumb(d)} alt="" loading="lazy" />
            {:else}<Icon name={d.status === 'processing' ? 'refresh' : d.category ?? 'file'} size={22} />{/if}
          </span>
          <span class="info">
            <span class="title">{d.title}</span>
            <span class="meta tiny muted">
              {#if d.category}<span>{categoryName(d.category)}</span>{/if}
              {#if d.doc_type}<span>{d.doc_type}</span>{/if}
              <span>{personName(d.person_id)}</span>
              {#if d.doc_date}<span>{fmtDate(d.doc_date)}</span>{/if}
              {#if d.amount_cents != null}<span>{fmtAmount(d.amount_cents)}</span>{/if}
              {#if d.issuer}<span>{d.issuer}</span>{/if}
            </span>
            {#if d.snippet}<span class="snippet tiny">{@html snippetHtml(d.snippet)}</span>{/if}
            <span class="badges">
              {#if d.status === 'processing'}<span class="badge">{t('doc.processing')}</span>{/if}
              {#if d.status === 'review'}<span class="badge warn"><Icon name="alert" size={12} />{t('doc.to_fix')}: {reasonText(d.review_reason)}</span>
              {:else if !d.category && d.status !== 'processing'}<span class="badge warn"><Icon name="alert" size={12} />{t('doc.no_category')}</span>{/if}
              {#if exp}<span class="badge" class:danger={exp.level === 'expired'} class:primary={exp.level === 'soon'}>{exp.text}</span>{/if}
            </span>
          </span>
        </a>
      </li>
    {/each}
  </ul>
  {#if more}<button class="btn block soft moreb" onclick={() => load(true)}>{t('archive.more', { n: total - items.length })}</button>{/if}
{/if}

{#if !f.trash && facets?.trash}
  <p class="center trashlink"><button class="btn ghost sm" onclick={() => (f.trash = '1')}><Icon name="trash" size={14} />{t('archive.trash_n', { n: facets.trash })}</button></p>
{/if}

<style>
  .head { display: flex; flex-direction: column; gap: 14px; margin-bottom: 12px; }
  .searchbox .input { min-height: 46px; font-size: 1rem; }
  .filters { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
  .selects { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  @media (min-width: 700px) { .selects { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  .selects .input { min-height: 36px; padding: 4px 10px; font-size: 0.88rem; }
  .status-line { margin: 6px 0 8px; min-height: 32px; }
  .docs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border: 1px solid var(--line);
    border-radius: var(--r-lg); background: var(--surface); overflow: hidden; }
  .docs li + li { border-top: 1px solid var(--line); }
  .doc { display: flex; gap: 12px; padding: 12px 14px; text-decoration: none; color: inherit; }
  .doc:hover { background: var(--surface-2); }
  .thumb { width: 48px; height: 64px; flex-shrink: 0; border-radius: var(--r-xs); border: 1px solid var(--line); background: var(--surface-2);
    display: grid; place-items: center; color: var(--muted); overflow: hidden; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; object-position: top; }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .title { font-weight: 600; overflow-wrap: anywhere; }
  .meta { display: flex; flex-wrap: wrap; gap: 0 10px; }
  .meta span + span::before { content: '·'; margin-right: 10px; }
  .snippet { color: var(--muted); overflow-wrap: anywhere; }
  .snippet :global(mark) { background: var(--primary-soft); color: var(--ink); border-radius: 3px; padding: 0 2px; }
  .badges { display: flex; flex-wrap: wrap; gap: 6px; }
  .badges:empty { display: none; }
  .center { justify-content: center; text-align: center; }
  .first { margin-top: 14px; }
  .moreb { margin-top: 12px; }
  .trashlink { margin-top: 18px; }
</style>

<script>
  // One document: preview, the original, its details (editable, category and person with one tap), the text read from it.
  import { del, get, post, put } from '../lib/api.js';
  import { app, loadFacets, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { CATEGORIES, amountInput, categoryName, expiryInfo, fmtSize, reasonText, typeSuggestions } from '../lib/docs.js';
  import { fmtDate } from '../lib/date.js';
  import Sheet from './Sheet.svelte';
  import Icon from './Icon.svelte';

  let { id, onclose } = $props();
  let doc = $state(null);
  let form = $state(null);
  let saving = $state(false);
  let showText = $state(false);

  function fill(d) {
    doc = d;
    form = {
      title: d.title, category: d.category ?? '', doc_type: d.doc_type, person_id: d.person_id ?? '', doc_date: d.doc_date ?? '',
      expiry_date: d.expiry_date ?? '', amount: amountInput(d.amount_cents), issuer: d.issuer, notes: d.notes,
    };
  }
  async function load() {
    try { fill(await get(`/documents/${id}`)); } catch (e) { showError(e); onclose(); }
  }
  load();
  // While it is being read, check again until done
  $effect(() => {
    if (doc?.status !== 'processing') return;
    const timer = setInterval(async () => {
      try {
        const d = await get(`/documents/${id}`);
        // Keep what the user already typed
        if (d.status !== 'processing') { if (dirty) doc = d; else fill(d); }
      } catch { /* try again */ }
    }, 2500);
    return () => clearInterval(timer);
  });

  const dirty = $derived(doc && form && (
    form.title !== doc.title || (form.category || null) !== doc.category || form.doc_type !== doc.doc_type ||
    (form.person_id || null) !== doc.person_id || (form.doc_date || null) !== doc.doc_date ||
    (form.expiry_date || null) !== doc.expiry_date || form.amount !== amountInput(doc.amount_cents) ||
    form.issuer !== doc.issuer || form.notes !== doc.notes));

  async function save(close = true) {
    saving = true;
    try {
      fill(await put(`/documents/${id}`, { ...form, person_id: form.person_id || null, category: form.category || null }));
      toast(t('common.saved'));
      loadFacets();
      if (close) onclose();
    } catch (e) { showError(e); } finally { saving = false; }
  }
  async function markFixed() {
    await save(false);
  }
  async function reprocess() {
    try { fill(await post(`/documents/${id}/reprocess`)); toast(t('doc.reprocessing')); } catch (e) { showError(e); }
  }
  async function trash() {
    try {
      await del(`/documents/${id}`);
      toast(t('doc.trashed'), 'ok', { label: t('common.undo'), run: async () => { await post(`/documents/${id}/restore`); loadFacets(); app.version = null; } });
      loadFacets();
      onclose();
    } catch (e) { showError(e); }
  }
  async function restore() {
    try { fill(await post(`/documents/${id}/restore`)); toast(t('doc.restored')); loadFacets(); } catch (e) { showError(e); }
  }
  async function destroy() {
    if (!confirm(t('doc.confirm_destroy', { title: doc.title }))) return;
    try { await del(`/documents/${id}?permanent=1`); toast(t('doc.destroyed')); loadFacets(); onclose(); } catch (e) { showError(e); }
  }
  async function copyText() {
    try { await navigator.clipboard.writeText(doc.ocr_text); toast(t('common.copied')); } catch { /* text stays visible */ }
  }
  function tryClose() {
    if (dirty && !confirm(t('doc.confirm_discard'))) return;
    onclose();
  }

  const types = $derived(typeSuggestions(form?.category, app.facets?.doc_types ?? []));
  const exp = $derived(expiryInfo(doc?.expiry_date));
  const fileUrl = $derived(`/api/documents/${id}/file`);
  const SOURCES = { upload: 'source.upload', scan: 'source.scan', shortcut: 'source.shortcut', email: 'source.email', api: 'source.api' };
</script>

<Sheet title={doc?.title ?? t('common.wait')} onclose={tryClose} wide>
  {#if doc && form}
    <div class="layout">
      <div class="side stack">
        <a class="preview" href={fileUrl} target="_blank" rel="noopener" title={t('doc.open_original')}>
          {#if doc.has_preview}<img src="/api/documents/{id}/preview?v={encodeURIComponent(doc.updated_at)}" alt={t('doc.preview')} />
          {:else}<span class="nopreview"><Icon name={doc.status === 'processing' ? 'refresh' : 'file'} size={34} />
            <span class="tiny">{doc.status === 'processing' ? t('doc.processing') : doc.file_name}</span></span>{/if}
        </a>
        <div class="row wrap">
          <a class="btn soft sm grow" href={fileUrl} target="_blank" rel="noopener"><Icon name="external" size={15} />{t('doc.open')}</a>
          <a class="btn soft sm grow" href="{fileUrl}?download=1"><Icon name="download" size={15} />{t('doc.download')}</a>
        </div>
        <p class="tiny muted facts">
          {doc.file_name} · {fmtSize(doc.size)}{#if doc.pages} · {t(doc.pages === 1 ? 'doc.one_page' : 'doc.pages', { n: doc.pages })}{/if}<br />
          {#if doc.origin}
            {t(SOURCES[doc.origin.source] ?? 'source.upload')}{#if doc.origin.email_from} · {doc.origin.email_from}{/if}
            {#if doc.origin.email_subject}<br />«{doc.origin.email_subject}»{/if}<br />
          {/if}
          {t('doc.added_by', { name: doc.created_by_name ?? '?', date: fmtDate(doc.created_at.slice(0, 10)) })}
          {#if doc.duplicates_received}<br />{t(doc.duplicates_received === 1 ? 'doc.duplicate_received' : 'doc.duplicates_received', { n: doc.duplicates_received })}{/if}
        </p>
      </div>

      <div class="main stack">
        {#if doc.deleted_at}
          <div class="banner"><Icon name="trash" size={16} /><span class="grow">{t('doc.in_trash')}</span>
            <button class="btn sm" onclick={restore}>{t('doc.restore')}</button></div>
        {:else if doc.status === 'review'}
          <div class="banner"><Icon name="alert" size={16} />
            <span class="grow"><b>{t('doc.to_fix')}:</b> {reasonText(doc.review_reason)}. {t('doc.to_fix_hint')}</span></div>
        {:else if doc.status === 'processing'}
          <div class="banner"><Icon name="refresh" size={16} /><span class="grow">{t('doc.processing_hint')}</span></div>
        {/if}

        <label class="field"><span class="label">{t('doc.title')}</span>
          <input class="input" bind:value={form.title} maxlength="200" /></label>

        <div class="field"><span class="label">{t('doc.category')}</span>
          <div class="chips">
            {#each CATEGORIES as c}
              <button type="button" class="chip" class:on={form.category === c} onclick={() => (form.category = form.category === c ? '' : c)}>
                <Icon name={c} size={14} />{categoryName(c)}</button>
            {/each}
          </div>
        </div>

        <div class="field"><span class="label">{t('doc.person')}</span>
          <div class="chips">
            <button type="button" class="chip" class:on={!form.person_id} onclick={() => (form.person_id = '')}>{t('doc.whole_family')}</button>
            {#each app.me.people as p (p.id)}
              <button type="button" class="chip" class:on={form.person_id === p.id} onclick={() => (form.person_id = p.id)}>{p.name}</button>
            {/each}
          </div>
        </div>

        <div class="grid2">
          <label class="field"><span class="label">{t('doc.type')}</span>
            <input class="input" bind:value={form.doc_type} list="doc-types" maxlength="100" placeholder={types[0] ?? ''} />
            <datalist id="doc-types">{#each types as x}<option value={x}></option>{/each}</datalist></label>
          <label class="field"><span class="label">{t('doc.issuer')}</span>
            <input class="input" bind:value={form.issuer} list="issuers" maxlength="150" placeholder={t('doc.issuer_ph')} />
            <datalist id="issuers">{#each app.facets?.issuers ?? [] as x}<option value={x}></option>{/each}</datalist></label>
          <label class="field"><span class="label">{t('doc.date')}</span>
            <input class="input" type="date" bind:value={form.doc_date} /></label>
          <label class="field"><span class="label">{t('doc.expiry')}</span>
            <input class="input" type="date" bind:value={form.expiry_date} />
            {#if exp && form.expiry_date === doc.expiry_date}<span class="tiny" class:danger={exp.level === 'expired'}>{exp.text}</span>{/if}</label>
          <label class="field"><span class="label">{t('doc.amount')}</span>
            <input class="input" bind:value={form.amount} inputmode="decimal" placeholder="0,00 €" maxlength="20" /></label>
        </div>

        <label class="field"><span class="label">{t('doc.notes')}</span>
          <textarea class="input" bind:value={form.notes} maxlength="10000"></textarea></label>

        <div class="field">
          <button class="linkish" onclick={() => (showText = !showText)}>
            {showText ? t('doc.hide_text') : t('doc.show_text')}
            {#if doc.text_source}<span class="muted tiny">({t('textsource.' + doc.text_source)})</span>{/if}
          </button>
          {#if showText}
            {#if doc.ocr_text}
              <pre class="ocr">{doc.ocr_text}</pre>
              <button class="btn ghost sm self" onclick={copyText}><Icon name="copy" size={14} />{t('common.copy')}</button>
            {:else}<p class="small muted">{t('doc.no_text')}</p>{/if}
          {/if}
        </div>

        <div class="row wrap more">
          {#if !doc.deleted_at}
            <button class="btn ghost sm" onclick={reprocess} disabled={doc.status === 'processing'}><Icon name="refresh" size={15} />{t('doc.reprocess')}</button>
            <button class="btn ghost sm" onclick={trash}><Icon name="trash" size={15} />{t('doc.trash')}</button>
          {:else}
            <button class="btn danger sm" onclick={destroy}><Icon name="trash" size={15} />{t('doc.destroy')}</button>
          {/if}
        </div>
      </div>
    </div>
  {:else}
    <p class="muted">{t('common.wait')}</p>
  {/if}
  {#snippet footer()}
    {#if doc && !doc.deleted_at}
      <button class="btn grow" onclick={tryClose}>{t('common.close')}</button>
      {#if doc.status === 'review' && !dirty}
        <button class="btn primary grow" onclick={markFixed} disabled={saving}><Icon name="check" size={16} />{t('doc.mark_fixed')}</button>
      {:else}
        <button class="btn primary grow" onclick={() => save()} disabled={saving || !dirty}>{t('common.save')}</button>
      {/if}
    {/if}
  {/snippet}
</Sheet>

<style>
  .layout { display: grid; gap: 18px; grid-template-columns: minmax(0, 1fr); }
  @media (min-width: 900px) { .layout { grid-template-columns: 220px minmax(0, 1fr); } }
  .preview { display: block; border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; background: var(--surface-2);
    max-height: 320px; }
  @media (max-width: 899px) { .preview { max-width: 220px; margin: 0 auto; width: 100%; } }
  .preview img { width: 100%; display: block; }
  .nopreview { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 36px 12px; color: var(--muted);
    text-align: center; overflow-wrap: anywhere; }
  .facts { line-height: 1.6; overflow-wrap: anywhere; }
  .banner { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: var(--r-sm); background: var(--primary-soft);
    font-size: 0.9rem; }
  .banner :global(svg) { margin-top: 2px; }
  .grid2 { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  @media (max-width: 520px) { .grid2 { grid-template-columns: minmax(0, 1fr); } }
  .ocr { margin: 6px 0 0; padding: 10px; max-height: 300px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
    background: var(--surface-2); border-radius: var(--r-sm); font-size: 0.8rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .linkish { border: 0; background: none; padding: 0; color: var(--primary); cursor: pointer; font: inherit; font-weight: 500; text-align: left; }
  .self { align-self: flex-start; }
  .more { border-top: 1px solid var(--line); padding-top: 10px; }
  .danger { color: var(--danger); }
</style>

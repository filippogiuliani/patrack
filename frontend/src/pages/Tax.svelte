<script>
  // The year's expenses for the tax return (730), grouped by kind and person, and the ZIP for the CAF.
  // It collects, it does not compute deductions (see backend/api_tax.py).
  import { get, put } from '../lib/api.js';
  import { app, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { fmtAmount } from '../lib/docs.js';
  import { fmtDate } from '../lib/date.js';
  import Icon from '../components/Icon.svelte';

  let year = $state(new Date().getFullYear() - 1); // the return is for last year
  let data = $state(null);
  let open = $state({});

  async function load() {
    try { data = await get(`/tax?year=${year}`); } catch (e) { showError(e); }
  }
  $effect(() => { year; app.version; load(); });

  // Receipts on A4 for the CAF: one PDF per person, because the 730 is one per tax code
  let codes = $state({});
  $effect(() => { codes = Object.fromEntries((data?.receipts ?? []).filter((r) => r.person_id).map((r) => [r.person_id, r.tax_code ?? ''])); });
  async function saveCode(r) {
    const code = (codes[r.person_id] || '').replace(/\s+/g, '').toUpperCase();
    if (code === (r.tax_code ?? '')) return;
    try { const res = await put(`/tax/people/${r.person_id}`, { tax_code: code }); r.tax_code = res.tax_code; codes[r.person_id] = res.tax_code ?? ''; toast(t('common.saved')); }
    catch (e) { showError(e); codes[r.person_id] = r.tax_code ?? ''; }
  }

  const docLabel = (d) => d.doc_type || d.title;
  const toggle = (kind) => (open = { ...open, [kind]: !open[kind] });
</script>

<header class="head">
  <div class="spread wrap">
    <h1>{t('nav.tax')}</h1>
    {#if data}
      <select class="input year" bind:value={year} aria-label={t('tax.year')}>
        {#each data.years as y}<option value={y}>{y}</option>{/each}
      </select>
    {/if}
  </div>
  <p class="muted">{t('tax.subtitle')}</p>
</header>

{#if data}
  {#if !data.kinds.length && !data.missing_date.length}
    <p class="empty">{t('tax.empty', { year: data.year })}</p>
  {:else}
    <section class="card total">
      <div>
        <div class="muted small">{t('tax.total', { year: data.year })}</div>
        <div class="big">{fmtAmount(data.total_cents)}</div>
      </div>
      {#if data.kinds.length}
        <a class="btn primary" href="/api/tax/export?year={data.year}" download><Icon name="download" size={17} />{t('tax.export')}</a>
      {/if}
    </section>
    <p class="tiny muted">{t('tax.export_note')}</p>

    <div class="kinds">
    {#each data.kinds as k (k.kind)}
      <section class="card kind">
        <button class="kind-head" onclick={() => toggle(k.kind)} aria-expanded={!!open[k.kind]}>
          <span class="grow"><b>{t('tax.kind.' + k.kind)}</b><span class="muted small"> · {t('tax.docs', { n: k.count })}</span></span>
          <b>{fmtAmount(k.total_cents)}</b>
          <Icon name={open[k.kind] ? 'left' : 'right'} size={16} />
        </button>
        {#if k.people.length > 1 || k.people[0]?.person_id}
          <div class="people small">
            {#each k.people as p (p.person_id)}<span>{p.name ?? t('doc.whole_family')}: <b>{fmtAmount(p.total_cents)}</b></span>{/each}
          </div>
        {/if}
        {#if open[k.kind]}
          <ul class="docs">
            {#each k.documents as d (d.id)}
              <li><a href="#/doc/{d.id}">
                <span class="grow">{docLabel(d)}<span class="muted small"> · {fmtDate(d.doc_date)}{d.person ? ' · ' + d.person : ''}{d.issuer ? ' · ' + d.issuer : ''}</span>
                  {#if !d.chosen}<span class="tag">{t('tax.proposed')}</span>{/if}</span>
                <span>{d.amount_cents == null ? '—' : fmtAmount(d.amount_cents)}</span>
              </a></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/each}
    </div>

    {#if data.receipts?.some((r) => r.count)}
      <section class="card receipts">
        <h2><Icon name="print" size={18} />{t('tax.receipts')}</h2>
        <p class="small muted">{t('tax.receipts_note')}</p>
        <ul class="plist">
          {#each data.receipts.filter((r) => r.person_id) as r (r.person_id)}
            <li>
              <span class="pname"><b>{r.name}</b><span class="muted small"> · {t('tax.receipts_n', { n: r.count })}</span></span>
              <input class="input cf" bind:value={codes[r.person_id]} maxlength="16" placeholder={t('tax.tax_code')} aria-label={t('tax.tax_code_of', { name: r.name })}
                     onchange={() => saveCode(r)} autocapitalize="characters" spellcheck="false" />
              {#if r.count}
                <a class="btn sm" href="/api/tax/receipts?year={data.year}&person={r.person_id}" download><Icon name="download" size={15} />PDF</a>
              {:else}<span class="btn sm ghost" aria-disabled="true">PDF</span>{/if}
            </li>
          {/each}
        </ul>
        {#if data.receipts.find((r) => !r.person_id)}
          <p class="small warnline"><Icon name="alert" size={15} />{t('tax.receipts_nobody', { n: data.receipts.find((r) => !r.person_id).count })}</p>
        {/if}
      </section>
    {/if}

    {#if data.missing_amount.length || data.missing_date.length}
      <section class="card warn">
        <h2><Icon name="alert" size={18} />{t('tax.to_complete')}</h2>
        {#each [['missing_amount', 'tax.missing_amount'], ['missing_date', 'tax.missing_date']] as [key, label]}
          {#if data[key].length}
            <p class="small muted">{t(label)}</p>
            <ul class="docs">
              {#each data[key] as d (d.id)}
                <li><a href="#/doc/{d.id}"><span class="grow">{docLabel(d)}<span class="muted small"> · {t('tax.kind.' + d.kind)}</span></span>
                  <Icon name="edit" size={15} /></a></li>
              {/each}
            </ul>
          {/if}
        {/each}
      </section>
    {/if}
  {/if}
{/if}

<style>
  .year { width: auto; }
  .total { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
  .big { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
  .kinds { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
  @media (min-width: 1100px) {
    .kinds { display: block; columns: 3 360px; column-gap: 12px; }
    .kinds > .kind { break-inside: avoid; margin: 0 0 12px; }
  }
  .kind { padding: 0; overflow: hidden; }
  .kind-head { display: flex; align-items: center; gap: 10px; width: 100%; padding: 14px 16px; border: 0; background: none; font: inherit;
    color: var(--ink); text-align: left; cursor: pointer; }
  .kind-head:hover { background: var(--surface-2); }
  .people { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 0 16px 12px; color: var(--muted); }
  .docs { list-style: none; margin: 0; padding: 0 8px 8px; }
  .docs a { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: var(--r-sm, 8px); text-decoration: none; color: var(--ink); }
  .docs a:hover { background: var(--surface-2); }
  .grow { flex: 1; min-width: 0; }
  .tag { margin-left: 6px; padding: 1px 6px; border-radius: 6px; background: var(--surface-2); color: var(--muted); font-size: 0.75rem; }
  .receipts { margin-top: 16px; }
  .receipts h2, .warn h2 { display: flex; align-items: center; gap: 8px; font-size: 1rem; }
  .plist { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; }
  .plist li { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0; border-top: 1px solid var(--line); }
  .pname { flex: 1; min-width: 10rem; }
  .cf { width: 13.5rem; max-width: 100%; font-family: ui-monospace, monospace; text-transform: uppercase; }
  .warnline { display: flex; align-items: center; gap: 6px; color: var(--muted); margin: 8px 0 0; }
  .warn { margin-top: 16px; }
  .warn h2 { display: flex; align-items: center; gap: 8px; font-size: 1rem; }
  .warn .docs { padding: 0; }
</style>

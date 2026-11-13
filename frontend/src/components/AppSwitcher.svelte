<script>
  // Switching between the family apps (weHub mode): weHub's home and the apps this person may use in this family.
  // The same file is in doTrack, eaTrack and paTrack. The list comes from /api/me → hub.apps (see famkit/hub.py).
  import { get } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  let { hub, label = false } = $props();
  let open = $state(false);
  let root;
  // Right after an update the server may not have the list yet (it is fetching it from weHub): ask once more shortly
  let later = $state(null);
  $effect(() => {
    if (!hub || hub.apps?.length || later) return;
    const timer = setTimeout(() => get('/me').then((m) => (later = m.hub?.apps ?? [])).catch(() => {}), 4000);
    return () => clearTimeout(timer);
  });
  const apps = $derived(hub?.apps?.length ? hub.apps : (later ?? []));
  const KNOWN = ['dotrack', 'eatrack', 'patrack'];

  function outside(e) {
    if (open && root && !root.contains(e.target)) open = false;
  }
  function key(e) {
    if (e.key === 'Escape') open = false;
  }
</script>

<svelte:window onclick={outside} onkeydown={key} />

{#if hub && apps.length}
  <div class="switcher" bind:this={root}>
    <button class="trigger" class:with-label={label} onclick={() => (open = !open)} aria-expanded={open} aria-haspopup="menu"
      aria-label={t('nav.apps')} title={t('nav.apps')}>
      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" />
        <rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" />
      </svg>
      {#if label}<span>{t('nav.apps')}</span>{/if}
    </button>
    {#if open}
      <div class="menu" role="menu">
        <a class="item" role="menuitem" href={hub.url}>
          <img src="/apps/wehub.svg" alt="" width="28" height="28" />
          <span><b>weHub</b><small>{t('nav.home')}</small></span>
        </a>
        {#each apps as a (a.id)}
          <a class="item" class:current={a.current} role="menuitem" href={a.current ? '#/' : a.url}
            aria-current={a.current ? 'page' : undefined} onclick={() => (open = false)}>
            {#if KNOWN.includes(a.id)}<img src="/apps/{a.id}.svg" alt="" width="28" height="28" />
            {:else}<span class="generic">{a.name.slice(0, 1)}</span>{/if}
            <span><b>{a.name}</b></span>
            {#if a.current}<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>{/if}
          </a>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .switcher { position: relative; }
  .trigger { display: flex; align-items: center; gap: 10px; white-space: nowrap; border: 0; background: none; color: var(--ink-2, var(--ink)); cursor: pointer;
    padding: 8px; border-radius: var(--r-sm, 8px); font: inherit; font-size: 0.92rem; }
  .trigger.with-label { width: 100%; padding: 9px 12px; }
  .trigger:hover, .trigger[aria-expanded='true'] { background: var(--surface-2); color: var(--ink); }
  .menu { position: absolute; z-index: 50; top: calc(100% + 6px); left: 0; min-width: 220px; padding: 6px;
    background: var(--surface, #fff); border: 1px solid var(--line); border-radius: var(--r, 12px); box-shadow: 0 10px 30px rgb(0 0 0 / 0.14); }
  :global(.topbar) .menu { left: auto; right: 0; }
  .item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--r-sm, 8px); text-decoration: none; color: var(--ink); }
  .item:hover { background: var(--surface-2); }
  .item.current { background: var(--primary-soft); }
  .item img, .generic { border-radius: 7px; flex-shrink: 0; }
  .generic { display: grid; place-items: center; width: 28px; height: 28px; background: var(--primary); color: var(--primary-ink, #fff); font-weight: 650; }
  .item span { display: flex; flex-direction: column; line-height: 1.2; flex: 1; }
  .item small { color: var(--ink-3, var(--ink-2)); font-size: 0.8rem; }
  .check { color: var(--primary); flex-shrink: 0; }
</style>

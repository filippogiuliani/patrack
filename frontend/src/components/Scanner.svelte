<script>
  // Scan paper documents with the camera: photo → corners found automatically (draggable) → straightened page.
  // Several pages become one PDF, sent to the import queue like any other file.
  import { t } from '../lib/i18n.svelte.js';
  import { app, showError, toast } from '../lib/store.svelte.js';
  import { canvasToJpeg, detectCorners, enhance, fullFrame, loadImage, makePdf, warp } from '../lib/scan.js';
  import { sendFiles } from '../lib/uploads.svelte.js';
  import Icon from './Icon.svelte';

  let { onclose } = $props();

  let pages = $state([]); // { blob, url, width, height }
  let source = $state(null); // canvas of the photo being cropped
  let corners = $state([]);
  let preview = $state(''); // data URL of the photo, for display
  let mode = $state('doc'); // doc (black and white, clean) | color
  let busy = $state(false);
  let title = $state('');
  let personId = $state('');
  let camera = $state(), gallery = $state(), svg = $state();

  async function picked(e) {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = '';
    if (!file) return;
    busy = true;
    try {
      source = await loadImage(file);
      corners = detectCorners(source);
      preview = source.toDataURL('image/jpeg', 0.7);
    } catch { showError(new Error(t('scan.unreadable'))); } finally { busy = false; }
  }

  // Dragging a corner: pointer position → image pixels
  let dragging = -1;
  function toImage(e) {
    const r = svg.getBoundingClientRect();
    return {
      x: Math.min(Math.max(((e.clientX - r.left) / r.width) * source.width, 0), source.width),
      y: Math.min(Math.max(((e.clientY - r.top) / r.height) * source.height, 0), source.height),
    };
  }
  function down(i, e) { dragging = i; e.currentTarget.setPointerCapture?.(e.pointerId); e.preventDefault(); }
  function move(e) { if (dragging >= 0) corners[dragging] = toImage(e); }
  function up() { dragging = -1; }

  async function confirmCrop() {
    busy = true;
    try {
      await new Promise((r) => setTimeout(r, 20)); // let the spinner show
      const page = warp(source, corners);
      if (mode === 'doc') enhance(page);
      const blob = await canvasToJpeg(page);
      pages.push({ blob, url: URL.createObjectURL(blob), width: page.width, height: page.height });
      source = null; preview = '';
    } catch (e) { showError(e); } finally { busy = false; }
  }
  function removePage(i) {
    URL.revokeObjectURL(pages[i].url);
    pages.splice(i, 1);
  }
  function movePage(i, d) {
    const j = i + d;
    if (j < 0 || j >= pages.length) return;
    [pages[i], pages[j]] = [pages[j], pages[i]];
  }

  async function save() {
    busy = true;
    try {
      const pdf = await makePdf(pages);
      const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ').replace(':', '.');
      const name = (title.trim() || t('scan.default_name', { date: stamp })).replace(/[\\/:*?"<>|]/g, '-') + '.pdf';
      sendFiles([new File([pdf], name, { type: 'application/pdf' })],
                { source: 'scan', title: title.trim() || undefined, person_id: personId || undefined });
      toast(t('scan.sent', { n: pages.length }));
      close();
    } catch (e) { showError(e); } finally { busy = false; }
  }

  function close() {
    for (const p of pages) URL.revokeObjectURL(p.url);
    onclose();
  }
  function cancel() {
    if (pages.length && !confirm(t('scan.confirm_discard', { n: pages.length }))) return;
    close();
  }
  const points = $derived(corners.map((c) => `${c.x},${c.y}`).join(' '));
</script>

<div class="scanner" role="dialog" aria-modal="true" aria-label={t('scan.title')}>
  <header>
    <button class="btn ghost sm" onclick={cancel}>{t('common.cancel')}</button>
    <h2>{t('scan.title')}</h2>
    <span class="count muted small">{t('scan.pages', { n: pages.length })}</span>
  </header>

  <input bind:this={camera} type="file" accept="image/*" capture="environment" hidden onchange={picked} />
  <input bind:this={gallery} type="file" accept="image/*" hidden onchange={picked} />

  <div class="body">
    {#if source}
      <p class="small muted hint">{t('scan.adjust')}</p>
      <div class="stage">
        <svg bind:this={svg} viewBox="0 0 {source.width} {source.height}" onpointermove={move} onpointerup={up} onpointercancel={up}
             role="presentation">
          <image href={preview} width={source.width} height={source.height} />
          <polygon points={points} class="quad" />
          {#each corners as c, i}
            <circle cx={c.x} cy={c.y} r={Math.max(source.width, source.height) / 28} class="handle"
                    onpointerdown={(e) => down(i, e)} role="slider" aria-label={t('scan.corner')} aria-valuenow={i} tabindex="-1" />
          {/each}
        </svg>
      </div>
      <div class="row wrap center">
        <div class="seg" role="group" aria-label={t('scan.mode')}>
          <button class:on={mode === 'doc'} onclick={() => (mode = 'doc')}>{t('scan.mode_doc')}</button>
          <button class:on={mode === 'color'} onclick={() => (mode = 'color')}>{t('scan.mode_color')}</button>
        </div>
        <button class="btn ghost sm" onclick={() => (corners = fullFrame(source))}>{t('scan.whole_photo')}</button>
        <button class="btn ghost sm" onclick={() => (corners = detectCorners(source))}>{t('scan.detect_again')}</button>
      </div>
      <div class="row center actions">
        <button class="btn" onclick={() => { source = null; preview = ''; }}>{t('scan.retake')}</button>
        <button class="btn primary" onclick={confirmCrop} disabled={busy}><Icon name="check" size={16} />{t('scan.use_page')}</button>
      </div>
    {:else}
      {#if pages.length}
        <ol class="pages">
          {#each pages as p, i (p.url)}
            <li>
              <img src={p.url} alt={t('scan.page_n', { n: i + 1 })} />
              <div class="page-actions">
                <span class="small">{i + 1}</span>
                <button class="btn icon sm ghost" onclick={() => movePage(i, -1)} disabled={i === 0} aria-label={t('scan.move_up')}><Icon name="left" size={15} /></button>
                <button class="btn icon sm ghost" onclick={() => movePage(i, 1)} disabled={i === pages.length - 1} aria-label={t('scan.move_down')}><Icon name="right" size={15} /></button>
                <button class="btn icon sm ghost" onclick={() => removePage(i)} aria-label={t('common.delete')}><Icon name="trash" size={15} /></button>
              </div>
            </li>
          {/each}
        </ol>
      {:else}
        <div class="empty-scan">
          <Icon name="scan" size={44} />
          <p>{t('scan.intro')}</p>
          <p class="small muted">{t('scan.tip')}</p>
        </div>
      {/if}
      <div class="row center wrap actions">
        <button class="btn primary" onclick={() => camera.click()} disabled={busy}><Icon name="camera" size={17} />
          {pages.length ? t('scan.add_page') : t('scan.take_photo')}</button>
        <button class="btn" onclick={() => gallery.click()} disabled={busy}><Icon name="image" size={17} />{t('scan.from_gallery')}</button>
      </div>
      {#if pages.length}
        <div class="finish stack">
          <input class="input" bind:value={title} maxlength="150" placeholder={t('scan.title_placeholder')} aria-label={t('doc.title')} />
          <select class="input" bind:value={personId} aria-label={t('doc.person')}>
            <option value="">{t('scan.person_later')}</option>
            {#each app.me.people as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
          <button class="btn primary" onclick={save} disabled={busy}>{t('scan.save', { n: pages.length })}</button>
        </div>
      {/if}
    {/if}
    {#if busy}<p class="center muted small">{t('common.wait')}</p>{/if}
  </div>
</div>

<style>
  .scanner { position: fixed; inset: 0; z-index: 150; background: var(--bg); display: flex; flex-direction: column; }
  header { display: flex; align-items: center; gap: 10px; padding: calc(10px + env(safe-area-inset-top)) 12px 10px;
    border-bottom: 1px solid var(--line); background: var(--surface); }
  header h2 { flex: 1; text-align: center; }
  .count { min-width: 70px; text-align: right; }
  .body { flex: 1; overflow-y: auto; padding: 16px 16px calc(24px + env(safe-area-inset-bottom)); max-width: 760px; width: 100%; margin: 0 auto;
    display: flex; flex-direction: column; gap: 14px; }
  .hint { text-align: center; margin: 0; }
  .stage { display: flex; justify-content: center; }
  svg { max-width: 100%; max-height: 62dvh; touch-action: none; user-select: none; background: #222; border-radius: var(--r-sm); }
  .quad { fill: rgba(30, 58, 95, 0.18); stroke: var(--primary); stroke-width: 0.6%; vector-effect: non-scaling-stroke; }
  .quad { stroke-width: 2.5px; }
  .handle { fill: rgba(255, 255, 255, 0.85); stroke: var(--primary); stroke-width: 3px; vector-effect: non-scaling-stroke; cursor: grab; }
  .center { justify-content: center; text-align: center; }
  .actions { gap: 10px; }
  .pages { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
  .pages li { display: flex; flex-direction: column; gap: 4px; }
  .pages img { width: 100%; aspect-ratio: 0.72; object-fit: contain; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-xs); }
  .page-actions { display: flex; align-items: center; gap: 2px; }
  .page-actions .small { flex: 1; }
  .empty-scan { text-align: center; padding: 30px 10px 10px; color: var(--muted); display: flex; flex-direction: column; align-items: center; gap: 6px; }
  .empty-scan p { margin: 0; }
  .empty-scan p:first-of-type { color: var(--ink); }
  .finish { border-top: 1px solid var(--line); padding-top: 14px; }
</style>

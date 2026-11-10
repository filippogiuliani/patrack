<script>
  // Texts live in lib/privacy (a DRAFT to complete and have reviewed before going public)
  import { language, t } from '../lib/i18n.svelte.js';
  import TEXTS from '../lib/privacy/index.js';
  import AuthCard from '../components/AuthCard.svelte';
  const text = $derived(TEXTS[language.id] ?? TEXTS.en);
</script>

<AuthCard title={t('privacy.title')}>
  <div class="text">
    <p class="draft">{text.draft}</p>
    {#each text.sections as [title, body] (title)}
      <h3>{title}</h3>
      <p>{@html body}</p>
    {/each}
    <p class="muted small">{text.updated}</p>
  </div>
  <a class="btn" href="#/" onclick={(e) => { if (history.length > 1) { e.preventDefault(); history.back(); } }}>{t('common.back')}</a>
</AuthCard>

<style>
  .text { display: flex; flex-direction: column; gap: 8px; font-size: 0.92rem; }
  .text h3 { margin-top: 8px; }
  .draft { padding: 8px 12px; border-radius: var(--r-sm); background: var(--danger-soft); color: var(--danger); font-weight: 500; }
</style>

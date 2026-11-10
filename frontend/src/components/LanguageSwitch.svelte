<script>
  import { LANGUAGES, language, setLanguage, t } from '../lib/i18n.svelte.js';
  // onchoose: optional callback (e.g. to save the language in the profile)
  let { onchoose = null } = $props();
</script>

<label class="language">
  <span class="sr-only">{t('common.language')}</span>
  <select class="input" value={language.id} onchange={(e) => { setLanguage(e.currentTarget.value); onchoose?.(e.currentTarget.value); }}>
    {#each LANGUAGES as l (l.id)}<option value={l.id}>{l.name}</option>{/each}
  </select>
</label>

<style>
  .language select { min-height: 34px; padding: 4px 28px 4px 10px; width: auto; font-size: 0.85rem; }
</style>

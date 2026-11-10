<script>
  // Centered container for the sign-in pages
  let { title, subtitle = '', children } = $props();
</script>

<main class="auth">
  <div class="box">
    <a class="brand" href="#/"><img src="/icon.svg" alt="" width="32" height="32" /><span>paTrack</span></a>
    <div class="card stack">
      <div>
        <h1>{title}</h1>
        {#if subtitle}<p class="muted small">{subtitle}</p>{/if}
      </div>
      {@render children()}
    </div>
  </div>
</main>

<style>
  .auth { min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px; }
  .box { width: 100%; max-width: 400px; display: flex; flex-direction: column; gap: 20px; }
  .brand { display: flex; align-items: center; justify-content: center; gap: 10px; text-decoration: none; color: var(--ink); font-weight: 650; font-size: 1.2rem; letter-spacing: -0.02em; }
  .brand img { border-radius: 8px; }
  .card { padding: 24px; gap: 16px; }
  h1 { font-size: 1.3rem; margin-bottom: 4px; }
</style>

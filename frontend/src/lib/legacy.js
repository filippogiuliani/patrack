// The app was paTrack until 2026-11: what this browser kept under the old names (the language…) is copied to the
// new ones once. Imported first in main.js.
try {
  for (const key of Object.keys(localStorage)) {
    const next = key.replace(/^patrack\./, 'pelican.');
    if (next !== key) {
      if (localStorage.getItem(next) === null) localStorage.setItem(next, localStorage.getItem(key));
      localStorage.removeItem(key);
    }
  }
} catch { /* storage not available: nothing to carry over */ }

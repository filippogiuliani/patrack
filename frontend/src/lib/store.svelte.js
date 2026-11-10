// Shared state: session (user, family, people), the import queue counters and toasts.
import { get } from './api.js';
import { t } from './i18n.svelte.js';

export const app = $state({
  toast: null,
  me: null, // response of /api/me
  version: null, // family version last seen (see /api/sync): when it changes, open pages reload
  sync: { active: 0, errors: 0 }, // import queue on the server
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  scanner: false, // the camera scanner is open
  facets: null, // /documents/facets, refreshed with the version
});

export async function loadMe() {
  app.me = await get('/me');
  return app.me;
}

let toastId = 0;
export function toast(message, kind = 'ok', action = null) {
  const id = ++toastId;
  app.toast = { id, message, kind, action };
  setTimeout(() => { if (app.toast?.id === id) app.toast = null; }, action ? 6000 : kind === 'error' ? 5000 : 2600);
}
export function showError(e) { toast(e?.message || t('error.generic', { code: '' }), 'error'); }

export async function loadFacets() {
  try { app.facets = await get('/documents/facets'); } catch { /* shown elsewhere */ }
}

/** Name of a person of the family (or "Famiglia" for documents about everyone). */
export function personName(id) {
  if (!id) return t('doc.whole_family');
  return app.me?.people?.find((p) => p.id === id)?.name ?? '?';
}

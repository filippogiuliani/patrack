// Small wrapper around the backend JSON API
import { language, t } from './i18n.svelte.js';

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: { 'X-Language': language.id }, credentials: 'same-origin' };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch('/api' + path, opts);
  } catch {
    const e = new Error(t('error.network'));
    e.offline = true; // no connection: lib/actions.js queues the change
    throw e;
  }
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
  if (r.status === 401 && !['/login', '/me'].includes(path)) onUnauthorized();
  if (!r.ok) throw new Error(data?.error || t('error.generic', { code: r.status }));
  return data;
}

export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: 'POST', body: body ?? {} });
export const put = (p, body) => api(p, { method: 'PUT', body });
export const del = (p, body) => api(p, { method: 'DELETE', body });

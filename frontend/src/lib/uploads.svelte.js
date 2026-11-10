// Files leaving this device. Each file is sent on its own (a few at a time), with progress.
// A file that cannot be sent stays here with the reason and a "Riprova" button: the browser still holds it,
// so nothing has to be chosen again. Once the server has it, the server's import queue takes over.
import { language, t } from './i18n.svelte.js';
import { app } from './store.svelte.js';

const PARALLEL = 3;
const MAX_MB = 50;

export const uploads = $state({ items: [] });
let seq = 0;

/** Add files to send. `opts`: { source, person_id, category, title } */
export function sendFiles(files, opts = {}) {
  for (const file of files) {
    uploads.items.unshift({ key: ++seq, file, name: file.name || 'file', size: file.size, state: 'waiting', progress: 0,
                            error: '', result: null, opts });
  }
  pump();
}

export function retryUpload(item) {
  item.state = 'waiting'; item.error = ''; item.progress = 0;
  pump();
}
export function forgetUpload(item) {
  uploads.items = uploads.items.filter((u) => u !== item);
}
export function retryAllUploads() {
  for (const u of uploads.items) if (u.state === 'failed') { u.state = 'waiting'; u.error = ''; }
  pump();
}

export const pendingUploads = () => uploads.items.filter((u) => u.state === 'waiting' || u.state === 'uploading').length;
export const failedUploads = () => uploads.items.filter((u) => u.state === 'failed').length;

function pump() {
  const busy = uploads.items.filter((u) => u.state === 'uploading').length;
  const next = uploads.items.filter((u) => u.state === 'waiting').reverse().slice(0, PARALLEL - busy);
  for (const item of next) send(item);
}

function send(item) {
  item.state = 'uploading';
  if (item.size > MAX_MB * 1024 * 1024) return fail(item, t('upload.too_large', { mb: MAX_MB }));
  const form = new FormData();
  form.append('file', item.file, item.name);
  for (const [k, v] of Object.entries(item.opts)) if (v !== undefined && v !== null && v !== '') form.append(k, v);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/imports');
  xhr.setRequestHeader('X-Language', language.id);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) item.progress = e.loaded / e.total; };
  xhr.onload = () => {
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
    if (xhr.status === 201) {
      item.state = 'sent';
      item.result = data;
      // The server's queue shows it from now on
      setTimeout(() => forgetUpload(item), 1500);
      app.version = null; // reload what is shown
    } else if (xhr.status === 413) fail(item, t('upload.too_large', { mb: MAX_MB }));
    else fail(item, data?.error || t('error.generic', { code: xhr.status }));
    pump();
  };
  xhr.onerror = () => { fail(item, t('upload.network')); pump(); };
  xhr.ontimeout = xhr.onerror;
  xhr.send(form);
}

function fail(item, message) {
  item.state = 'failed';
  item.error = message;
}

// Leaving the page while files are still going would lose them
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (e) => {
    if (pendingUploads()) { e.preventDefault(); e.returnValue = ''; }
  });
}

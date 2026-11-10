"""The import queue: every file that arrives (browser, scan, iPhone Shortcut, email) goes through intake(), which
stores the original right away and queues it; a background worker then reads it (text, OCR, preview).

Rules:
- the original is stored before anything else can go wrong, byte for byte (encrypted at rest);
- every file leaves a row in `imports` with its outcome: nothing fails silently;
- if reading fails the document is still in the archive, marked "da sistemare", and the import can be retried;
- the same file (same SHA-256) already in the family's archive is reported as a duplicate, not stored twice."""
import datetime
import hashlib
import os
import threading
import time
import traceback
import uuid

from flask import Blueprint, abort, g, jsonify, request

import db
import processing
import search
import storage
from common import text

bp = Blueprint('imports', __name__)

MAX_FILE = int(os.environ.get('PATRACK_MAX_FILE_MB', '50')) * 1024 * 1024
MAX_ATTEMPTS_AUTO = 1  # the worker never retries on its own: the user sees the error and taps "Riprova"
_wake = threading.Event()

IMPORT_FIELDS = '''i.id, i.source, i.file_name, i.size, i.status, i.error, i.error_detail, i.attempts, i.document_id,
                   i.duplicate_of, i.email_from, i.email_subject, i.created_at, i.updated_at, i.user_id,
                   d.title AS document_title, d.status AS document_status, d.review_reason, d.deleted_at AS document_deleted,
                   dd.title AS duplicate_title, dd.deleted_at AS duplicate_deleted, u.name AS user_name'''
IMPORT_JOIN = '''FROM imports i LEFT JOIN documents d ON d.id = i.document_id LEFT JOIN documents dd ON dd.id = i.duplicate_of
                 LEFT JOIN users u ON u.id = i.user_id'''


def title_from_name(name):
    base = os.path.splitext(os.path.basename(name or ''))[0]
    base = base.replace('_', ' ').strip()
    return base[:200] or 'Documento'


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def intake(conn, family_id, user_id, source, file_name, data, *, batch=None, email_from=None, email_subject=None,
           force=False, title=None, person_id=None, category=None):
    """Store one received file and queue it. Returns the id of the import row (always created)."""
    file_name = text(file_name, 200) or 'file'
    row = {'family_id': family_id, 'user_id': user_id, 'source': source, 'file_name': file_name, 'size': len(data or b''),
           'batch': batch, 'email_from': email_from, 'email_subject': text(email_subject, 300) or None}

    def record(status, error=None, detail=None, document_id=None, duplicate_of=None):
        return conn.execute('''INSERT INTO imports (family_id, user_id, source, file_name, size, status, error, error_detail,
                               document_id, duplicate_of, batch, email_from, email_subject) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (family_id, user_id, source, file_name, row['size'], status, error, detail, document_id,
                             duplicate_of, batch, email_from, row['email_subject'])).lastrowid

    if not data:
        return record('error', 'empty_file')
    if len(data) > MAX_FILE:
        return record('error', 'too_large', f'{len(data) // (1024 * 1024)} MB')
    sha = hashlib.sha256(data).hexdigest()
    if not force:
        dup = conn.execute('SELECT id FROM documents WHERE family_id = ? AND sha256 = ? ORDER BY deleted_at IS NOT NULL, id LIMIT 1',
                           (family_id, sha)).fetchone()
        if dup:
            return record('duplicate', duplicate_of=dup['id'])
    try:
        stored = storage.put(data)
    except Exception as e:
        print(f'[import] storing {file_name} failed: {e}', flush=True)
        return record('error', 'storage_failed', str(e))
    mime = processing.sniff_mime(data, file_name)
    doc_id = conn.execute('''INSERT INTO documents (family_id, title, category, person_id, file_name, mime, size, sha256,
                             stored_name, created_by) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                          (family_id, text(title, 200) or title_from_name(file_name), category, person_id, file_name, mime,
                           len(data), sha, stored, user_id)).lastrowid
    search.index(conn, conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone())
    iid = record('queued', document_id=doc_id)
    db.bump(conn, family_id)
    return iid


def wake():
    _wake.set()


# ======================================================================
# Worker
# ======================================================================

def process_one():
    """Process the oldest queued import. Returns its id, or None when the queue is empty."""
    with db.transaction() as conn:
        job = conn.execute("SELECT * FROM imports WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        if not job:
            return None
        conn.execute("UPDATE imports SET status = 'processing', attempts = attempts + 1, updated_at = ? WHERE id = ?",
                     (_now(), job['id']))
        doc = conn.execute('SELECT * FROM documents WHERE id = ?', (job['document_id'],)).fetchone() if job['document_id'] else None
        db.bump(conn, job['family_id'])

    status, error, detail, result = 'done', None, None, None
    if not doc:
        status, error = 'error', 'document_missing'
    else:
        try:
            data = storage.get(doc['stored_name'])
        except Exception as e:
            data = None
            status, error, detail = 'error', 'file_unreadable', str(e)
        if data is not None:
            try:
                result = processing.process(data, doc['mime'])
            except processing.ProcessingError as e:
                status, error, detail = 'error', e.key, e.detail
            except Exception as e:
                traceback.print_exc()
                status, error, detail = 'error', 'processing_failed', f'{type(e).__name__}: {e}'

    with db.transaction() as conn:
        if doc:
            current = conn.execute('SELECT * FROM documents WHERE id = ?', (doc['id'],)).fetchone()
            if current:
                if result is not None:
                    preview = current['preview_name']
                    if result['preview']:
                        try:
                            new_preview = storage.put(result['preview'])
                            if preview:
                                storage.delete(preview)
                            preview = new_preview
                        except Exception as e:
                            print(f'[import] preview of document {doc["id"]} not saved: {e}', flush=True)
                    reason = result['problems'][0] if result['problems'] else None
                    conn.execute('''UPDATE documents SET ocr_text = ?, text_source = ?, pages = ?, preview_name = ?, status = ?,
                                    review_reason = ?, updated_at = datetime('now') WHERE id = ?''',
                                 (result['text'], result['text_source'], result['pages'], preview,
                                  'review' if reason else 'ready', reason, doc['id']))
                else:
                    # Reading failed: the document stays in the archive, "da sistemare"
                    conn.execute("UPDATE documents SET status = 'review', review_reason = ? WHERE id = ?", (error, doc['id']))
                search.index(conn, conn.execute('SELECT * FROM documents WHERE id = ?', (doc['id'],)).fetchone())
        conn.execute('UPDATE imports SET status = ?, error = ?, error_detail = ?, updated_at = ? WHERE id = ?',
                     (status, error, detail, _now(), job['id']))
        db.bump(conn, job['family_id'])
    if error:
        print(f'[import] #{job["id"]} {job["file_name"]}: {error} {detail or ""}', flush=True)
    if job['batch']:
        batch_finished(job['batch'])
    return job['id']


def batch_finished(batch):
    """When every file of an email has an outcome, the sender gets a summary (see mailin)."""
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM imports WHERE batch = ? AND status IN ('queued', 'processing')", (batch,)).fetchone():
            return
    import mailin
    mailin.send_summary(batch)


def purge_trash():
    """Documents in the trash for more than TRASH_DAYS days are deleted for good, with their files."""
    with db.transaction() as conn:
        old = conn.execute(f"SELECT id FROM documents WHERE deleted_at < datetime('now', '-{db.TRASH_DAYS} days')").fetchall()
    for r in old:
        delete_document(r['id'])


def delete_document(doc_id):
    with db.transaction() as conn:
        d = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
        if not d:
            return
        search.unindex(conn, doc_id)
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        db.bump(conn, d['family_id'])
    storage.delete(d['stored_name'])
    if d['preview_name']:
        storage.delete(d['preview_name'])


def start_worker():
    def loop():
        last_purge = 0
        while True:
            try:
                while process_one():
                    pass
                if time.time() - last_purge > 6 * 3600:
                    purge_trash()
                    last_purge = time.time()
            except Exception:  # the worker must never die
                traceback.print_exc()
            _wake.wait(30)
            _wake.clear()

    threading.Thread(target=loop, daemon=True, name='import-worker').start()


# ======================================================================
# API
# ======================================================================

def _int(value):
    try:
        return int(value) if value not in (None, '', 'null') else None
    except (TypeError, ValueError):
        return None


@bp.post('/imports')
def upload():
    """One file per request (multipart, field "file"). Optional: source, title, person_id, category, force."""
    f = request.files.get('file')
    if f is None:
        abort(400, 'No file uploaded')
    source = request.form.get('source')
    if getattr(g, 'via_token', False):
        source = source if source in ('shortcut', 'api') else 'shortcut'
    elif source not in ('upload', 'scan'):
        source = 'upload'
    data = f.read(MAX_FILE + 1)
    with db.transaction() as conn:
        person_id = _int(request.form.get('person_id'))
        if person_id and not conn.execute('SELECT 1 FROM people WHERE id = ? AND family_id = ?', (person_id, g.family_id)).fetchone():
            person_id = None
        category = request.form.get('category') if request.form.get('category') in db.CATEGORIES else None
        iid = intake(conn, g.family_id, g.user['id'], source, f.filename or 'file', data,
                     force=request.form.get('force') in ('1', 'true'), title=request.form.get('title'),
                     person_id=person_id, category=category)
        row = _import_row(conn, iid)
    wake()
    return jsonify(row), 201


def _import_row(conn, iid):
    r = conn.execute(f'SELECT {IMPORT_FIELDS} {IMPORT_JOIN} WHERE i.id = ? AND i.family_id = ?', (iid, g.family_id)).fetchone()
    if not r:
        abort(404, 'Import not found')
    return dict(r)


@bp.get('/imports')
def list_imports():
    """The queue: the last imports not dismissed, newest first, and the counts by status."""
    with db.transaction() as conn:
        items = [dict(r) for r in conn.execute(
            f'SELECT {IMPORT_FIELDS} {IMPORT_JOIN} WHERE i.family_id = ? AND i.dismissed = 0 ORDER BY i.id DESC LIMIT 300',
            (g.family_id,))]
        counts = {r['status']: r['n'] for r in conn.execute(
            'SELECT status, COUNT(*) AS n FROM imports WHERE family_id = ? AND dismissed = 0 GROUP BY status', (g.family_id,))}
    return jsonify(items=items, counts=counts)


@bp.get('/imports/<int:iid>')
def get_import(iid):
    with db.transaction() as conn:
        return jsonify(_import_row(conn, iid))


@bp.post('/imports/<int:iid>/retry')
def retry(iid):
    """Read the stored file again. Imports that never stored a file cannot be retried here (the browser re-sends it)."""
    with db.transaction() as conn:
        r = _import_row(conn, iid)
        if r['status'] in ('queued', 'processing'):
            return jsonify(r)
        if not r['document_id']:
            abort(400, 'The file was not received: send it again')
        conn.execute("UPDATE imports SET status = 'queued', error = NULL, error_detail = NULL, dismissed = 0, updated_at = ? "
                     'WHERE id = ?', (_now(), iid))
        conn.execute("UPDATE documents SET status = 'processing', review_reason = NULL WHERE id = ?", (r['document_id'],))
        db.bump(conn, g.family_id)
        row = _import_row(conn, iid)
    wake()
    return jsonify(row)


@bp.post('/imports/retry-all')
def retry_all():
    with db.transaction() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM imports WHERE family_id = ? AND status = 'error' AND document_id IS NOT NULL",
                                          (g.family_id,))]
        for iid in ids:
            conn.execute("UPDATE imports SET status = 'queued', error = NULL, error_detail = NULL, dismissed = 0 WHERE id = ?", (iid,))
        conn.execute(f"UPDATE documents SET status = 'processing', review_reason = NULL WHERE id IN "
                     f"(SELECT document_id FROM imports WHERE id IN ({','.join('?' * len(ids))}))", ids)
        db.bump(conn, g.family_id)
    wake()
    return jsonify(retried=len(ids))


@bp.post('/imports/<int:iid>/keep')
def keep_duplicate(iid):
    """A duplicate the user wants anyway: a new document with a copy of the same file."""
    with db.transaction() as conn:
        r = _import_row(conn, iid)
        if r['status'] != 'duplicate' or not r['duplicate_of']:
            abort(400, 'Not a duplicate')
        d = conn.execute('SELECT * FROM documents WHERE id = ? AND family_id = ?', (r['duplicate_of'], g.family_id)).fetchone()
        if not d:
            abort(404, 'Document not found')
        data = storage.get(d['stored_name'])
        new_id = intake(conn, g.family_id, g.user['id'], r['source'], r['file_name'], data, force=True)
        conn.execute('UPDATE imports SET dismissed = 1 WHERE id = ?', (iid,))
        row = _import_row(conn, new_id)
    wake()
    return jsonify(row), 201


@bp.post('/imports/<int:iid>/dismiss')
def dismiss(iid):
    with db.transaction() as conn:
        _import_row(conn, iid)
        conn.execute('UPDATE imports SET dismissed = 1 WHERE id = ?', (iid,))
        db.bump(conn, g.family_id)
    return jsonify(ok=True)


@bp.post('/imports/dismiss-done')
def dismiss_done():
    """Clear the finished rows (errors stay until they are retried or dismissed one by one)."""
    with db.transaction() as conn:
        conn.execute("UPDATE imports SET dismissed = 1 WHERE family_id = ? AND status IN ('done', 'duplicate')", (g.family_id,))
        db.bump(conn, g.family_id)
    return jsonify(ok=True)


def new_batch():
    return uuid.uuid4().hex

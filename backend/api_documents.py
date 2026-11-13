"""API: the archive. List with filters and free-text search, details, edits, the original file, the trash."""
import datetime
import re
from urllib.parse import quote

from flask import Blueprint, Response, abort, g, jsonify, request

import db
import api_tax
import imports
import links
import processing
import search
import storage
from common import body, text, valid_date

bp = Blueprint('documents', __name__)

LIST_FIELDS = '''d.id, d.title, d.category, d.doc_type, d.person_id, d.doc_date, d.expiry_date, d.amount_cents, d.issuer,
                 d.status, d.review_reason, d.mime, d.size, d.pages, d.file_name, d.preview_name IS NOT NULL AS has_preview,
                 d.created_at, d.updated_at, d.deleted_at, d.dotrack, d.dotrack_state, d.eatrack_plan'''
SORTS = {'date': 'COALESCE(d.doc_date, date(d.created_at)) DESC, d.id DESC', 'added': 'd.id DESC',
         'expiry': 'd.expiry_date IS NULL, d.expiry_date, d.id DESC', 'title': 'd.title COLLATE NOCASE, d.id DESC'}
EXPIRY_SOON_DAYS = 60
PAGE = 60


def _doc(conn, doc_id, include_deleted=True):
    d = conn.execute('SELECT * FROM documents WHERE id = ? AND family_id = ?', (doc_id, g.family_id)).fetchone()
    if not d or (d['deleted_at'] and not include_deleted):
        abort(404, 'Document not found')
    return d


def _filters(conn, args):
    """WHERE conditions from the query string (shared by the list and the facets)."""
    conds, params = ['d.family_id = ?'], [g.family_id]
    conds.append('d.deleted_at IS NOT NULL' if args.get('trash') == '1' else 'd.deleted_at IS NULL')
    person = args.get('person')
    if person == 'family':
        conds.append('d.person_id IS NULL')
    elif person and person.isdigit():
        conds.append('d.person_id = ?')
        params.append(int(person))
    category = args.get('category')
    if category == 'none':
        conds.append('d.category IS NULL')
    elif category in db.CATEGORIES:
        conds.append('d.category = ?')
        params.append(category)
    year = args.get('year')
    if year and re.fullmatch(r'\d{4}', year):
        conds.append("strftime('%Y', COALESCE(d.doc_date, d.created_at)) = ?")
        params.append(year)
    expiry = args.get('expiry')
    today = datetime.date.today()
    if expiry == 'expired':
        conds.append('d.expiry_date < ?')
        params.append(today.isoformat())
    elif expiry == 'soon':
        conds.append('d.expiry_date BETWEEN ? AND ?')
        params += [today.isoformat(), (today + datetime.timedelta(days=EXPIRY_SOON_DAYS)).isoformat()]
    elif expiry == 'any':
        conds.append('d.expiry_date IS NOT NULL')
    if args.get('status') == 'review':
        conds.append("(d.status = 'review' OR d.category IS NULL)")
    elif args.get('status') == 'processing':
        conds.append("d.status = 'processing'")
    snippet = None
    q = text(args.get('q'), 200)
    if q:
        c, p, snippet = search.build(q, db.people(conn, g.family_id))
        conds += c
        params += p
    return conds, params, snippet


def _snippets(conn, ids, expr):
    """A short extract around the words searched, for each document found."""
    if not ids or not expr:
        return {}
    out = {}
    try:
        for r in conn.execute(f'''SELECT rowid, snippet(documents_fts, 4, '[[', ']]', '…', 14) AS s FROM documents_fts
                                  WHERE documents_fts MATCH ? AND rowid IN ({','.join('?' * len(ids))})''', [expr, *ids]):
            if '[[' in (r['s'] or ''):
                out[r['rowid']] = r['s']
    except Exception:
        pass
    return out


@bp.get('/documents')
def list_documents():
    args = request.args
    with db.transaction() as conn:
        conds, params, snippet_expr = _filters(conn, args)
        where = ' AND '.join(conds)
        try:
            offset = max(0, int(args.get('offset', 0)))
        except ValueError:
            offset = 0
        order = SORTS.get(args.get('sort'), SORTS['date'])
        total = conn.execute(f'SELECT COUNT(*) FROM documents d WHERE {where}', params).fetchone()[0]
        items = [dict(r) for r in conn.execute(f'SELECT {LIST_FIELDS} FROM documents d WHERE {where} ORDER BY {order} '
                                               f'LIMIT {PAGE} OFFSET {offset}', params)]
        snippets = _snippets(conn, [i['id'] for i in items], snippet_expr)
    for i in items:
        i['has_preview'] = bool(i['has_preview'])
        if i['id'] in snippets:
            i['snippet'] = snippets[i['id']]
    return jsonify(items=items, total=total, offset=offset, page=PAGE)


@bp.get('/documents/facets')
def facets():
    """What the filters can offer: years, counts per category and person, how many to fix, expiring."""
    today = datetime.date.today()
    with db.transaction() as conn:
        base = 'family_id = ? AND deleted_at IS NULL'
        p = (g.family_id,)
        years = [r[0] for r in conn.execute(f"SELECT DISTINCT strftime('%Y', COALESCE(doc_date, created_at)) AS y FROM documents "
                                            f'WHERE {base} ORDER BY y DESC', p)]
        categories = {r[0] or 'none': r[1] for r in conn.execute(f'SELECT category, COUNT(*) FROM documents WHERE {base} GROUP BY category', p)}
        people = {str(r[0] or 'family'): r[1] for r in conn.execute(f'SELECT person_id, COUNT(*) FROM documents WHERE {base} GROUP BY person_id', p)}
        review = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {base} AND (status = 'review' OR category IS NULL)", p).fetchone()[0]
        expired = conn.execute(f'SELECT COUNT(*) FROM documents WHERE {base} AND expiry_date < ?', (*p, today.isoformat())).fetchone()[0]
        soon = conn.execute(f'SELECT COUNT(*) FROM documents WHERE {base} AND expiry_date BETWEEN ? AND ?',
                            (*p, today.isoformat(), (today + datetime.timedelta(days=EXPIRY_SOON_DAYS)).isoformat())).fetchone()[0]
        total = conn.execute(f'SELECT COUNT(*) FROM documents WHERE {base}', p).fetchone()[0]
        trash = conn.execute('SELECT COUNT(*) FROM documents WHERE family_id = ? AND deleted_at IS NOT NULL', p).fetchone()[0]
        doc_types = [r[0] for r in conn.execute(f"SELECT doc_type FROM documents WHERE {base} AND doc_type != '' "
                                                'GROUP BY doc_type ORDER BY COUNT(*) DESC LIMIT 200', p)]
        issuers = [r[0] for r in conn.execute(f"SELECT issuer FROM documents WHERE {base} AND issuer != '' "
                                              'GROUP BY issuer ORDER BY COUNT(*) DESC LIMIT 200', p)]
    return jsonify(years=years, categories=categories, people=people, review=review, expired=expired, soon=soon, total=total,
                   trash=trash, doc_types=doc_types, issuers=issuers)


@bp.get('/documents/<int:doc_id>')
def get_document(doc_id):
    with db.transaction() as conn:
        d = dict(_doc(conn, doc_id))
        origin = conn.execute('''SELECT i.id, i.source, i.email_from, i.email_subject, i.created_at, i.status, i.error, u.name AS user_name
                                 FROM imports i LEFT JOIN users u ON u.id = i.user_id WHERE i.document_id = ? ORDER BY i.id LIMIT 1''',
                              (doc_id,)).fetchone()
        creator = conn.execute('SELECT name FROM users WHERE id = ?', (d['created_by'],)).fetchone() if d['created_by'] else None
        duplicates = conn.execute('''SELECT COUNT(*) FROM imports WHERE duplicate_of = ? AND status = 'duplicate' ''', (doc_id,)).fetchone()[0]
    d['tax_guess'] = api_tax.guess(d)   # what "proposed" means for this document
    d['has_preview'] = bool(d.pop('preview_name'))
    for k in ('stored_name', 'family_id'):
        d.pop(k)
    d['origin'] = dict(origin) if origin else None
    d['created_by_name'] = creator['name'] if creator else None
    d['duplicates_received'] = duplicates
    return jsonify(d)


def _amount(value):
    """Euro amount from 12.50, "12,50", "1.234,56" → cents (None when empty)."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return round(float(value) * 100)
    s = str(value).strip().replace('€', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return round(float(s) * 100)
    except ValueError:
        abort(400, 'Invalid amount')


@bp.put('/documents/<int:doc_id>')
def update_document(doc_id):
    """Edit the fields. Saving a document that was "da sistemare" marks it as fixed."""
    d = body()
    with db.transaction() as conn:
        cur = _doc(conn, doc_id)
        fields, sync = {}, False
        if 'title' in d:
            fields['title'] = text(d['title'], 200) or cur['title']
        if 'category' in d:
            if d['category'] not in (None, '', *db.CATEGORIES):
                abort(400, 'Invalid category')
            fields['category'] = d['category'] or None
        if 'doc_type' in d:
            fields['doc_type'] = text(d['doc_type'], 100)
        if 'issuer' in d:
            fields['issuer'] = text(d['issuer'], 150)
        if 'notes' in d:
            fields['notes'] = text(d['notes'], 10000)
        if 'person_id' in d:
            pid = d['person_id']
            if pid in (None, '', 0):
                fields['person_id'] = None
            else:
                if not conn.execute('SELECT 1 FROM people WHERE id = ? AND family_id = ?', (pid, g.family_id)).fetchone():
                    abort(400, 'Invalid person')
                fields['person_id'] = int(pid)
        for k in ('doc_date', 'expiry_date'):
            if k in d:
                fields[k] = valid_date(d[k], k) if d[k] else None
        if 'amount' in d:
            fields['amount_cents'] = _amount(d['amount'])
        if 'dotrack' in d:
            fields['dotrack'] = 1 if d['dotrack'] else 0
            if d['dotrack'] and not cur['dotrack']:
                fields['dotrack_by'] = g.user['id']
        if 'dotrack_remind' in d:
            r = d['dotrack_remind']
            if r in (None, ''):
                fields['dotrack_remind'] = None
            elif isinstance(r, int) and 0 <= r <= 365:
                fields['dotrack_remind'] = r
            else:
                abort(400, 'Invalid reminder')
        if 'eatrack_plan' in d:
            fields['eatrack_plan'] = 1 if d['eatrack_plan'] else 0
        if 'tax_kind' in d:
            if d['tax_kind'] not in (None, '', api_tax.NONE, *api_tax.KINDS):
                abort(400, 'Invalid kind')
            fields['tax_kind'] = d['tax_kind'] or None
        if cur['status'] == 'review':
            fields['status'], fields['review_reason'] = 'ready', None
        if fields:
            sets = ', '.join(f'{k} = ?' for k in fields)
            conn.execute(f"UPDATE documents SET {sets}, updated_at = datetime('now') WHERE id = ?", (*fields.values(), doc_id))
            search.index(conn, conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone())
            # doTrack shows the title/type, the date, the person and the reminder: tell it when one of them changed
            shown = ('title', 'doc_type', 'person_id', 'expiry_date', 'category', 'dotrack', 'dotrack_remind')
            sync = (fields.get('dotrack', cur['dotrack']) or cur['dotrack_item']) and \
                any(k in fields and fields[k] != cur[k] for k in shown)
            if sync:
                links.mark(conn, doc_id)
            db.bump(conn, g.family_id)
    if fields and sync:
        links.push_deadline(doc_id)
    return get_document(doc_id)


@bp.post('/documents/<int:doc_id>/reprocess')
def reprocess(doc_id):
    """Read the file again (text, OCR, preview): a new row in the import queue."""
    with db.transaction() as conn:
        d = _doc(conn, doc_id, include_deleted=False)
        if d['status'] == 'processing':
            abort(409, 'Already being processed')
        conn.execute("UPDATE documents SET status = 'processing', review_reason = NULL WHERE id = ?", (doc_id,))
        conn.execute('''INSERT INTO imports (family_id, user_id, source, file_name, size, status, document_id)
                        VALUES (?,?,?,?,?, 'queued', ?)''', (g.family_id, g.user['id'], 'api', d['file_name'], d['size'], doc_id))
        db.bump(conn, g.family_id)
    imports.wake()
    return get_document(doc_id)


@bp.delete('/documents/<int:doc_id>')
def delete_document(doc_id):
    """To the trash (kept 30 days); with ?permanent=1 from the trash, deleted for good with the file."""
    with db.transaction() as conn:
        d = _doc(conn, doc_id)
        if request.args.get('permanent') != '1':
            conn.execute("UPDATE documents SET deleted_at = datetime('now') WHERE id = ?", (doc_id,))
            if d['dotrack_item']:
                links.mark(conn, doc_id)   # its deadline goes away in doTrack too
            db.bump(conn, g.family_id)
            if d['dotrack_item']:
                links.wake()
            return jsonify(ok=True)
        if not d['deleted_at']:
            abort(400, 'Move it to the trash first')
    imports.delete_document(doc_id)
    return jsonify(ok=True)


@bp.post('/documents/<int:doc_id>/restore')
def restore(doc_id):
    with db.transaction() as conn:
        d = _doc(conn, doc_id)
        conn.execute('UPDATE documents SET deleted_at = NULL WHERE id = ?', (doc_id,))
        if d['dotrack']:
            links.mark(conn, doc_id)   # back from the trash: its deadline comes back (a new one) in doTrack
        db.bump(conn, g.family_id)
    if d['dotrack']:
        links.push_deadline(doc_id)
    return get_document(doc_id)


def _file_response(data, mime, name, download):
    inline = not download and mime in processing.INLINE_MIMES
    resp = Response(data, mimetype=mime if inline else (mime if download else 'application/octet-stream'))
    ascii_name = re.sub(r'[^\w.\- ]', '_', name)[:150] or 'file'
    resp.headers['Content-Disposition'] = (f"{'inline' if inline else 'attachment'}; filename=\"{ascii_name}\"; "
                                           f"filename*=UTF-8''{quote(name)}")
    resp.headers['Cache-Control'] = 'private, no-store'
    # Opened in its own tab: nothing in it may run scripts or reach other places
    resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; object-src 'self'"
    return resp


@bp.get('/documents/<int:doc_id>/file')
def original(doc_id):
    """The original file, exactly as received."""
    with db.transaction() as conn:
        d = _doc(conn, doc_id)
    try:
        data = storage.get(d['stored_name'])
    except Exception as e:
        print(f'[file] document {doc_id}: {e}', flush=True)
        abort(500)
    return _file_response(data, d['mime'], d['file_name'], request.args.get('download') == '1')


@bp.get('/documents/<int:doc_id>/preview')
def preview(doc_id):
    with db.transaction() as conn:
        d = _doc(conn, doc_id)
    if not d['preview_name']:
        abort(404, 'No preview')
    resp = Response(storage.get(d['preview_name']), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp

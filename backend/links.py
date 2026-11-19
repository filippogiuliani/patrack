"""Pelican and the other family apps (Wombat mode only; everything goes through Wombat, see famkit/hub.py).

- Kooka deadlines: on a document with an expiry date someone can ask "remind me in Kooka" (documents.kooka = 1,
  kooka_remind = the reminder N days before, NULL = none). Pelican then keeps a Kooka deadline in step with the document (title, date, person,
  link) and removes it when the document goes to the trash, loses its date or the reminder is turned off. When Kooka
  cannot be reached the change waits (kooka_state = 'pending') and is retried every few minutes. A deadline deleted
  in Kooka is not created again: the reminder is turned off here.
- From Kooka: a deadline's document can be sent here (POST /api/hub/families/<id>/documents): it is archived like
  any other file and its deadline is the one Pelican keeps in step from then on.
- Wallaby: documents marked as the paediatrician's plan of a child (documents.wallaby_plan) are listed in Wallaby's
  plan page (GET /api/hub/families/<id>/plans?child=<Wombat person id>)."""
import base64
import binascii
import threading
import time
import traceback

from flask import abort, g, jsonify, request

import auth
import db
import imports
from common import text, valid_date
from famkit import hub

RETRY_SECONDS = 300
_wake = threading.Event()


def doc_url(doc_id):
    return f"{auth.BASE_URL}/#/doc/{doc_id}" if auth.BASE_URL else None


def _hub_ids_of_person(conn, person_id):
    """{member_hub_id} for a member, {person_hub_id} for someone without an account, {} for the whole family."""
    if not person_id:
        return {}
    p = conn.execute('''SELECT p.hub_id, u.hub_id AS user_hub_id FROM people p LEFT JOIN users u ON u.id = p.user_id
                        WHERE p.id = ?''', (person_id,)).fetchone()
    if not p:
        return {}
    if p['user_hub_id']:
        return {'member_hub_id': p['user_hub_id']}
    return {'person_hub_id': p['hub_id']} if p['hub_id'] else {}


def _asking_user(conn, doc):
    """Wombat id of the member on whose behalf Pelican asks Kooka: who turned the reminder on, else any member."""
    for uid in (doc['kooka_by'], doc['created_by']):
        if uid:
            r = conn.execute('''SELECT u.hub_id FROM users u JOIN members m ON m.user_id = u.id AND m.family_id = ?
                                WHERE u.id = ? AND u.hub_id IS NOT NULL''', (doc['family_id'], uid)).fetchone()
            if r:
                return r['hub_id']
    r = conn.execute('''SELECT u.hub_id FROM members m JOIN users u ON u.id = m.user_id
                        WHERE m.family_id = ? AND u.hub_id IS NOT NULL ORDER BY m.role = 'admin' DESC LIMIT 1''',
                     (doc['family_id'],)).fetchone()
    return r['hub_id'] if r else None


# ======================================================================
# Kooka deadlines
# ======================================================================

def mark(conn, doc_id):
    """Something Kooka shows changed (or the reminder was turned on/off): to be sent."""
    conn.execute("UPDATE documents SET kooka_state = 'pending', kooka_error = NULL WHERE id = ?", (doc_id,))


def push_deadline(doc_id):
    """Bring Kooka in step with one document. Returns the new state ('sent', None, 'pending')."""
    with db.transaction() as conn:
        doc = conn.execute('''SELECT d.*, f.hub_id AS family_hub_id FROM documents d JOIN families f ON f.id = d.family_id
                              WHERE d.id = ?''', (doc_id,)).fetchone()
        if not doc or doc['kooka_state'] != 'pending':
            return doc['kooka_state'] if doc else None
        user_hub_id = _asking_user(conn, doc)
        who = _hub_ids_of_person(conn, doc['person_id'])
    wanted = doc['kooka'] and doc['expiry_date'] and not doc['deleted_at']
    ref = f'/deadlines/pelican-{doc_id}'
    state, item_id, error = None, doc['kooka_item'], None
    try:
        if not doc['family_hub_id'] or not user_hub_id:
            raise hub.AskError(404, 'This family is not linked to Wombat')
        if wanted:
            r = hub.ask('kooka', 'PUT', ref, doc['family_hub_id'], user_hub_id, {
                'title': doc['doc_type'] or doc['title'], 'due_date': doc['expiry_date'], 'remind_days': doc['kooka_remind'],
                'category': doc['category'], 'notes': f"Pelican: {doc['title']}", 'url': doc_url(doc_id), **who})
            if r.get('deleted'):
                # Someone deleted the deadline in Kooka: the reminder is off here too
                with db.transaction() as conn:
                    conn.execute('''UPDATE documents SET kooka = 0, kooka_state = NULL, kooka_item = NULL,
                                    kooka_error = NULL WHERE id = ?''', (doc_id,))
                    db.bump(conn, doc['family_id'])
                return None
            state, item_id = 'sent', r.get('item_id')
        elif doc['kooka_item']:
            hub.ask('kooka', 'DELETE', ref, doc['family_hub_id'], user_hub_id)
            item_id = None
    except hub.AskError as e:
        state, error = 'error', e.message          # refused: shown on the document, not retried by itself
    except hub.Unavailable as e:
        print(f'[kooka] document {doc_id}: {e}', flush=True)
        return 'pending'                            # retried later
    with db.transaction() as conn:
        # Only if nothing changed meanwhile (otherwise it is pending again and goes on the next round)
        conn.execute('''UPDATE documents SET kooka_state = ?, kooka_item = ?, kooka_error = ?
                        WHERE id = ? AND kooka_state = 'pending' AND updated_at = ?''',
                     (state, item_id, error, doc_id, doc['updated_at']))
        db.bump(conn, doc['family_id'])
    return state


def push_pending():
    with db.transaction() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE kooka_state = 'pending' ORDER BY id LIMIT 200")]
    for doc_id in ids:
        push_deadline(doc_id)


def wake():
    _wake.set()


def start_worker():
    if not hub.enabled():
        return

    def loop():
        while True:
            _wake.wait(RETRY_SECONDS)
            _wake.clear()
            time.sleep(0.5)   # let the request that woke us commit
            try:
                push_pending()
            except Exception:  # must never die
                traceback.print_exc()

    threading.Thread(target=loop, daemon=True, name='kooka-links').start()


# ======================================================================
# Asked by the other apps
# ======================================================================

def _can_read():
    """Pelican's answers carry documents: only for someone with full access (limited access comes with phase 4)."""
    if request.args.get('level') != 'full':
        abort(403, 'You do not use Pelican in this family')


def _person_from_hub(conn, d):
    if d.get('member_hub_id'):
        r = conn.execute('''SELECT p.id FROM people p JOIN users u ON u.id = p.user_id
                            WHERE p.family_id = ? AND u.hub_id = ?''', (g.family_id, d['member_hub_id'])).fetchone()
        if r:
            return r['id']
    if d.get('person_hub_id'):
        r = conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id = ?', (g.family_id, d['person_hub_id'])).fetchone()
        if r:
            return r['id']
    return None


@hub.service('/documents', methods=['POST'])
def from_kooka():
    """Kooka: {file_name, content (base64), title, expiry_date, remind_days, category, notes, kooka_item,
    member_hub_id | person_hub_id} → {id, url, duplicate}. The deadline stays in step from here on."""
    _can_read()
    d = request.get_json(silent=True) or {}
    try:
        data = base64.b64decode(d.get('content') or '', validate=True)
    except (binascii.Error, ValueError):
        abort(400, 'Invalid file')
    expiry = valid_date(d['expiry_date'], 'expiry_date') if d.get('expiry_date') else None
    remind = d.get('remind_days')
    remind = remind if isinstance(remind, int) and 0 <= remind <= 365 else None
    with db.transaction() as conn:
        iid = imports.intake(conn, g.family_id, g.user['id'], 'kooka', d.get('file_name'), data,
                             title=d.get('title'), person_id=_person_from_hub(conn, d),
                             category=d.get('category') if d.get('category') in db.CATEGORIES else None)
        row = conn.execute('SELECT status, error, document_id, duplicate_of FROM imports WHERE id = ?', (iid,)).fetchone()
        if row['status'] == 'error':
            abort(400, 'The file could not be archived')
        doc_id = row['document_id'] or row['duplicate_of']
        doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
        if row['duplicate_of'] and doc['kooka_item'] and doc['kooka_item'] != d.get('kooka_item'):
            abort(409, 'This document is already in Pelican with its own deadline')
        conn.execute('''UPDATE documents SET expiry_date = COALESCE(?, expiry_date), notes = CASE WHEN notes = '' THEN ? ELSE notes END,
                        kooka = 1, kooka_remind = ?, kooka_by = ?, kooka_item = ?, kooka_state = 'sent', kooka_error = NULL,
                        deleted_at = NULL WHERE id = ?''',
                     (expiry, text(d.get('notes'), 2000), remind, g.user['id'], d.get('kooka_item'), doc_id))
        db.bump(conn, g.family_id)
    imports.wake()
    return jsonify(id=doc_id, url=doc_url(doc_id), duplicate=bool(row['duplicate_of'])), 201


@hub.service('/plans')
def plans_for_wallaby():
    """Wallaby: the documents marked as the paediatrician's plan for a child (?child=<Wombat person id>), newest first."""
    _can_read()
    child = request.args.get('child', type=int)
    with db.transaction() as conn:
        rows = conn.execute('''SELECT d.id, d.title, d.doc_type, d.doc_date, d.issuer, d.created_at, substr(d.ocr_text, 1, 600) AS excerpt
                               FROM documents d JOIN people p ON p.id = d.person_id
                               WHERE d.family_id = ? AND p.hub_id = ? AND d.wallaby_plan = 1 AND d.deleted_at IS NULL
                               ORDER BY COALESCE(d.doc_date, date(d.created_at)) DESC, d.id DESC LIMIT 20''',
                            (g.family_id, child)).fetchall()
    return jsonify([{**dict(r), 'url': doc_url(r['id'])} for r in rows])


@hub.service('/summary')
def summary_for_wombat():
    """Wombat's home: {to_fix, errors, added_week, expiring: [{id, title, expiry_date, person, url}], url}."""
    import datetime
    _can_read()
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=60)).isoformat()
    with db.transaction() as conn:
        one = lambda sql, *a: conn.execute(sql, (g.family_id, *a)).fetchone()[0]  # noqa: E731
        to_fix = one("SELECT COUNT(*) FROM documents WHERE family_id = ? AND deleted_at IS NULL AND status = 'review'")
        errors = one("SELECT COUNT(*) FROM imports WHERE family_id = ? AND status = 'error' AND dismissed = 0")
        added = one("SELECT COUNT(*) FROM documents WHERE family_id = ? AND deleted_at IS NULL AND created_at >= ?",
                    (today - datetime.timedelta(days=7)).isoformat())
        rows = conn.execute('''SELECT d.id, d.title, d.doc_type, d.expiry_date, p.name AS person FROM documents d
                               LEFT JOIN people p ON p.id = d.person_id
                               WHERE d.family_id = ? AND d.deleted_at IS NULL AND d.expiry_date IS NOT NULL
                               AND d.expiry_date <= ? AND d.expiry_date >= ?
                               ORDER BY d.expiry_date LIMIT 5''',
                            (g.family_id, soon, (today - datetime.timedelta(days=30)).isoformat())).fetchall()
    return jsonify(to_fix=to_fix, errors=errors, added_week=added, url=auth.BASE_URL or None,
                   expiring=[{'id': r['id'], 'title': r['doc_type'] or r['title'], 'expiry_date': r['expiry_date'],
                              'person': r['person'], 'url': doc_url(r['id'])} for r in rows])

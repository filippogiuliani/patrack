"""weHub link: the family (members, roles, people, who may use this app) is defined in weHub.

Configuration (all optional; without them paTrack works on its own as before):
  DOTRACK_HUB_URL         weHub's address as this server reaches it, e.g. http://wehub:3004
  DOTRACK_HUB_KEY         shared key, the same as WEHUB_APP_PATRACK_KEY in weHub
  DOTRACK_HUB_PUBLIC_URL  weHub's address for people (links), default DOTRACK_HUB_URL
  DOTRACK_HUB_SYNC_SECONDS how often families are refreshed (default 120)

When on:
- sign-in only through the OIDC provider (the same Pocket ID as weHub); after it weHub says who the person is and
  which families they may use paTrack in. Those families are copied here (members, roles, people).
- the family, its members and people are changed only in weHub: those endpoints answer 409 here.
- families are refreshed every couple of minutes; if weHub is down, people who already signed in go on working.
- weHub reads this app's families once (GET /api/hub/export) to import them, then this app adopts its own rows."""
import hmac
import os
import threading
import time
import traceback

import requests
from flask import Blueprint, abort, jsonify, request

import db

PREFIX = 'PATRACK'
AGENT = 'paTrack'
URL = os.environ.get(f'{PREFIX}_HUB_URL', '').rstrip('/')
KEY = os.environ.get(f'{PREFIX}_HUB_KEY', '')
PUBLIC_URL = os.environ.get(f'{PREFIX}_HUB_PUBLIC_URL', '').rstrip('/')
INTERVAL = int(os.environ.get(f'{PREFIX}_HUB_SYNC_SECONDS', '120'))
TIMEOUT = 8
NO_PASSWORD = '!'

bp = Blueprint('hub', __name__)


def enabled():
    return bool(URL and KEY)


def guard():
    """For endpoints that change the family: in weHub mode they are not used here."""
    if enabled():
        abort(409, 'The family is managed in weHub')


def public_info():
    return {'url': PUBLIC_URL or URL, 'name': 'weHub'} if enabled() else None


class Unavailable(Exception):
    pass


class NoAccess(Exception):
    pass


def _call(method, path, payload=None):
    try:
        r = requests.request(method, f'{URL}/api/service{path}', json=payload, timeout=TIMEOUT, allow_redirects=False,
                             headers={'Authorization': f'Bearer {KEY}', 'User-Agent': AGENT})
    except requests.RequestException as e:
        raise Unavailable(f'{type(e).__name__}: {e}')
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise Unavailable(f'weHub answered {r.status_code}')
    return r.json()


# ---------- Sign-in ----------

def sign_in(provider, issuer, subject, email, email_verified, name):
    """The local user for someone who just signed in with the provider, their families updated from weHub.
    Raises NoAccess (not in a family that may use this app) or Unavailable (weHub down and never seen before)."""
    try:
        who = _call('POST', '/whoami', {'issuer': issuer, 'subject': subject, 'email': email,
                                        'email_verified': bool(email_verified), 'name': name})
    except Unavailable:
        with db.transaction() as conn:
            u = conn.execute('''SELECT u.* FROM identities i JOIN users u ON u.id = i.user_id
                                WHERE i.provider = ? AND i.subject = ? AND u.hub_id IS NOT NULL''', (provider, subject)).fetchone()
            if u and conn.execute('SELECT 1 FROM members WHERE user_id = ?', (u['id'],)).fetchone():
                return u
        raise
    if not who or not who.get('known') or not who.get('families'):
        raise NoAccess()
    with db.transaction() as conn:
        uid = _user(conn, who['user'])
        keep = {apply_family(conn, snap) for snap in who['families']}
        for (fid,) in conn.execute('''SELECT m.family_id FROM members m JOIN families f ON f.id = m.family_id
                                      WHERE m.user_id = ? AND f.hub_id IS NOT NULL''', (uid,)).fetchall():
            if fid not in keep:
                _remove_member(conn, fid, uid)
        return conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()


def _user(conn, u):
    """Local user id for a weHub user (by weHub id, then by email), created when missing."""
    r = conn.execute('SELECT id FROM users WHERE hub_id = ?', (u['hub_id'],)).fetchone() or \
        conn.execute('SELECT id FROM users WHERE email = ? AND hub_id IS NULL', (u['email'],)).fetchone()
    if r:
        uid = r['id']
        conn.execute('UPDATE users SET hub_id = ?, name = ?, email_verified = 1 WHERE id = ?', (u['hub_id'], u['name'], uid))
        if not conn.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (u['email'], uid)).fetchone():
            conn.execute('UPDATE users SET email = ? WHERE id = ?', (u['email'], uid))
        return uid
    return conn.execute("INSERT INTO users (email, name, password_hash, email_verified, language, consent_at, hub_id) "
                        "VALUES (?,?,?,1,?,datetime('now'),?)",
                        (u['email'], u['name'], NO_PASSWORD, u.get('language') or 'it', u['hub_id'])).lastrowid


def _remove_member(conn, family_id, user_id):
    conn.execute('DELETE FROM members WHERE family_id = ? AND user_id = ?', (family_id, user_id))
    on_member_removed(conn, family_id, user_id)
    # Signed out everywhere: their next request finds no session
    if not conn.execute('SELECT 1 FROM members WHERE user_id = ?', (user_id,)).fetchone():
        conn.execute('UPDATE users SET session_version = session_version + 1 WHERE id = ?', (user_id,))


def apply_family(conn, snap):
    """Make the local copy of a weHub family match the snapshot. Returns the local family id."""
    f = conn.execute('SELECT id FROM families WHERE hub_id = ?', (snap['hub_id'],)).fetchone()
    if not f and snap.get('local_id'):
        f = conn.execute('SELECT id FROM families WHERE id = ? AND hub_id IS NULL', (snap['local_id'],)).fetchone()
    if f:
        fid = f['id']
        conn.execute('UPDATE families SET hub_id = ?, hub_version = ?, name = ? WHERE id = ?',
                     (snap['hub_id'], snap['version'], snap['name'], fid))
    else:
        lang = next((m.get('language') for m in snap['members'] if m.get('language')), 'it')
        fid = db.create_family(conn, snap['name'], lang)
        conn.execute('UPDATE families SET hub_id = ?, hub_version = ? WHERE id = ?', (snap['hub_id'], snap['version'], fid))
    wanted = {}
    for m in snap['members']:
        uid = _user(conn, m)
        wanted[uid] = m['role']
        conn.execute('INSERT INTO members (family_id, user_id, role) VALUES (?,?,?) '
                     'ON CONFLICT(family_id, user_id) DO UPDATE SET role = excluded.role', (fid, uid, m['role']))
    for (uid,) in conn.execute('SELECT user_id FROM members WHERE family_id = ?', (fid,)).fetchall():
        if uid not in wanted:
            _remove_member(conn, fid, uid)
    apply_people(conn, fid, snap)
    bump(conn, fid)
    return fid


# ---------- Periodic refresh ----------

def sync_all():
    with db.transaction() as conn:
        fams = conn.execute('SELECT id, hub_id, hub_version FROM families WHERE hub_id IS NOT NULL').fetchall()
    for f in fams:
        snap = _call('GET', f"/families/{f['hub_id']}?version={f['hub_version'] or ''}")
        if snap is None:
            print(f"[hub] family {f['hub_id']} no longer exists in weHub: local copy kept as it is", flush=True)
            continue
        if snap.get('unchanged'):
            continue
        with db.transaction() as conn:
            apply_family(conn, snap)


def start_sync():
    if not enabled():
        return

    def loop():
        while True:
            time.sleep(INTERVAL)
            try:
                sync_all()
            except Unavailable as e:
                print(f'[hub] weHub not reachable: {e}', flush=True)
            except Exception:
                traceback.print_exc()

    threading.Thread(target=loop, daemon=True, name='hub-sync').start()
    print(f'[hub] family managed in weHub ({URL}), refreshed every {INTERVAL}s', flush=True)


# ---------- For weHub: what this app has (import) ----------

@bp.get('/hub/export')
def export():
    presented = request.headers.get('Authorization', '')[7:].strip()
    if not KEY or not hmac.compare_digest(KEY, presented):
        return jsonify(error='Unknown key'), 401
    out = []
    with db.transaction() as conn:
        for f in conn.execute('SELECT id, name, hub_id FROM families ORDER BY id').fetchall():
            members = [{'email': r['email'], 'name': r['name'], 'role': r['role']} for r in conn.execute(
                'SELECT u.email, u.name, m.role FROM members m JOIN users u ON u.id = m.user_id WHERE m.family_id = ?', (f['id'],))]
            out.append({'local_id': f['id'], 'name': f['name'], 'hub_id': f['hub_id'], 'members': members,
                        'people': export_people(conn, f['id'])})
    return jsonify(families=out)


# ======================================================================
# This app's people: everyone documents can be about (members and people without an account)
# ======================================================================

def bump(conn, family_id):
    db.bump(conn, family_id)


def apply_people(conn, family_id, snap):
    """Every weHub person is a paTrack person; members keep the link to their account. Someone removed in weHub:
    their documents become "the whole family"."""
    seen = set()
    for p in snap['people']:
        u = conn.execute('SELECT id FROM users WHERE hub_id = ?', (p['user_hub_id'],)).fetchone() if p.get('user_hub_id') else None
        uid = u['id'] if u and conn.execute('SELECT 1 FROM members WHERE family_id = ? AND user_id = ?',
                                            (family_id, u['id'])).fetchone() else None
        r = conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id = ?', (family_id, p['hub_id'])).fetchone()
        if not r and p.get('local_id'):
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND id = ? AND hub_id IS NULL', (family_id, p['local_id'])).fetchone()
        if not r and uid:
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND user_id = ? AND hub_id IS NULL', (family_id, uid)).fetchone()
        if not r:
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND hub_id IS NULL',
                             (family_id, p['name'])).fetchone()
        if r:
            pid = r['id']
            if uid:
                # Another row already stands for this member (made before weHub): merge it into this one
                other = conn.execute('SELECT id FROM people WHERE family_id = ? AND user_id = ? AND id != ?',
                                     (family_id, uid, pid)).fetchone()
                if other:
                    conn.execute('UPDATE documents SET person_id = ? WHERE person_id = ?', (pid, other['id']))
                    conn.execute('DELETE FROM people WHERE id = ?', (other['id'],))
            conn.execute('UPDATE people SET hub_id = ?, name = ?, birth_date = ?, user_id = ? WHERE id = ?',
                         (p['hub_id'], p['name'], p.get('birth_date'), uid, pid))
        else:
            if uid:
                conn.execute('UPDATE people SET user_id = NULL WHERE family_id = ? AND user_id = ?', (family_id, uid))
            pid = conn.execute('INSERT INTO people (family_id, user_id, name, birth_date, hub_id) VALUES (?,?,?,?,?)',
                               (family_id, uid, p['name'], p.get('birth_date'), p['hub_id'])).lastrowid
        seen.add(pid)
    for (pid,) in conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id IS NOT NULL', (family_id,)).fetchall():
        if pid not in seen:
            conn.execute('UPDATE documents SET person_id = NULL WHERE person_id = ?', (pid,))
            conn.execute('DELETE FROM people WHERE id = ?', (pid,))


def export_people(conn, family_id):
    rows = conn.execute('SELECT p.id, p.name, p.birth_date, u.email FROM people p '
                        'LEFT JOIN users u ON u.id = p.user_id WHERE p.family_id = ?', (family_id,))
    return [{'local_id': r['id'], 'name': r['name'], 'birth_date': r['birth_date'], 'member_email': r['email'], 'kind': 'adult'}
            for r in rows]


def on_member_removed(conn, family_id, user_id):
    conn.execute('UPDATE people SET user_id = NULL WHERE family_id = ? AND user_id = ?', (family_id, user_id))
    conn.execute('DELETE FROM api_tokens WHERE family_id = ? AND user_id = ?', (family_id, user_id))

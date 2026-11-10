"""API: family, members, people, invitations, addresses allowed to forward email, backup status."""
import json
import os

from flask import Blueprint, abort, g, jsonify, session

import db
import hub
import i18n
from auth import app_link, create_token, rate_limit, read_token, require_admin, use_token
from common import body, text, valid_date

bp = Blueprint('family', __name__)


@bp.get('/family')
def family():
    with db.transaction() as conn:
        f = conn.execute('SELECT id, name, created_at FROM families WHERE id = ?', (g.family_id,)).fetchone()
        members = [dict(r) for r in conn.execute('''SELECT u.id, u.name, u.email, m.role FROM members m JOIN users u ON u.id = m.user_id
                                                    WHERE m.family_id = ? ORDER BY m.created_at''', (g.family_id,))]
        people = db.people(conn, g.family_id)
        senders = [r[0] for r in conn.execute('SELECT email FROM mail_senders WHERE user_id = ? ORDER BY email', (g.user['id'],))]
    for m in members:
        m['me'] = m['id'] == g.user['id']
    import mailin
    return jsonify(**dict(f), members=members, people=people, role=g.role, mail_senders=senders,
                   inbox=mailin.status(), backup=backup_status())


def backup_status():
    """Local database backups and the off-site copy (written by scripts/backup-to-nas.sh into DATA_DIR/offsite.json)."""
    import backup
    local = backup.list_backups()
    offsite = None
    try:
        with open(os.path.join(db.DATA_DIR, 'offsite.json')) as f:
            offsite = json.load(f)
    except (OSError, ValueError):
        pass
    return {'last_local': local[0]['created_at'] if local else None, 'offsite': offsite}


# ---------- People without an account (kids, grandparents, babysitter…): any member can manage them ----------

MAX_PEOPLE = 50


def _person_name(conn, exclude=None):
    name = text(body().get('name'), 60)
    if not name:
        abort(400, 'Name is required')
    if conn.execute('SELECT 1 FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND id IS NOT ?',
                    (g.family_id, name, exclude)).fetchone():
        abort(409, 'There is already someone with this name')
    return name


def _birth():
    v = body().get('birth_date')
    return valid_date(v, 'birth_date') if v else None


@bp.post('/family/people')
def add_person():
    hub.guard()
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM people WHERE family_id = ?', (g.family_id,)).fetchone()[0] >= MAX_PEOPLE:
            abort(400, 'Too many people')
        name = _person_name(conn)
        pid = conn.execute('INSERT INTO people (family_id, name, birth_date) VALUES (?,?,?)', (g.family_id, name, _birth())).lastrowid
        return jsonify(db.people(conn, g.family_id)), 201


def _person(conn, pid):
    p = conn.execute('SELECT * FROM people WHERE id = ? AND family_id = ?', (pid, g.family_id)).fetchone()
    if not p:
        abort(404, 'Person not found')
    return p


@bp.put('/family/people/<int:pid>')
def rename_person(pid):
    hub.guard()
    with db.transaction() as conn:
        p = _person(conn, pid)
        if p['user_id']:
            name = p['name']  # a member's name comes from their account
        else:
            name = _person_name(conn, exclude=pid)
        conn.execute('UPDATE people SET name = ?, birth_date = ? WHERE id = ?', (name, _birth(), pid))
        return jsonify(db.people(conn, g.family_id))


@bp.delete('/family/people/<int:pid>')
def delete_person(pid):
    """Their documents become "the whole family"."""
    hub.guard()
    with db.transaction() as conn:
        p = _person(conn, pid)
        if p['user_id']:
            abort(400, 'A member cannot be removed from here')
        conn.execute('UPDATE documents SET person_id = NULL WHERE person_id = ?', (pid,))
        conn.execute('DELETE FROM people WHERE id = ?', (pid,))
        return jsonify(db.people(conn, g.family_id))


@bp.put('/family')
def rename():
    hub.guard()
    require_admin()
    name = text(body().get('name'), 80)
    if not name:
        abort(400, 'Name is required')
    with db.transaction() as conn:
        conn.execute('UPDATE families SET name = ? WHERE id = ?', (name, g.family_id))
    return jsonify(ok=True)


@bp.post('/family/switch')
def switch():
    try:
        family_id = int(body().get('family_id'))
    except (TypeError, ValueError):
        abort(400, 'invalid family_id')
    if not any(f['id'] == family_id for f in g.families):
        abort(404, 'Family not found')
    session['family_id'] = family_id
    return jsonify(ok=True)


@bp.post('/family/invites')
def create_invite():
    """Invitation link, valid for 7 days and usable once."""
    hub.guard()
    require_admin()
    rate_limit(f'invite:{g.user["id"]}', 20, 3600)
    with db.transaction() as conn:
        token, expires = create_token(conn, 'invite', 24 * 7, user_id=g.user['id'], family_id=g.family_id)
    return jsonify(link=app_link('invite/' + token), expires_at=expires), 201


@bp.delete('/family/members/<int:uid>')
def remove_member(uid):
    """An admin can remove a member; anyone can leave (uid = their own id)."""
    hub.guard()
    if uid != g.user['id']:
        require_admin()
    with db.transaction() as conn:
        members = conn.execute('SELECT user_id, role FROM members WHERE family_id = ? ORDER BY created_at', (g.family_id,)).fetchall()
        if not any(m['user_id'] == uid for m in members):
            abort(404, 'Member not found')
        others = [m for m in members if m['user_id'] != uid]
        if not others:
            abort(400, "You're the only member: to delete the family, delete your account")
        conn.execute('DELETE FROM members WHERE family_id = ? AND user_id = ?', (g.family_id, uid))
        # Their documents stay, about a person without an account; their tokens stop working here
        conn.execute('UPDATE people SET user_id = NULL WHERE family_id = ? AND user_id = ?', (g.family_id, uid))
        conn.execute('DELETE FROM api_tokens WHERE family_id = ? AND user_id = ?', (g.family_id, uid))
        if not any(m['role'] == 'admin' for m in others):
            conn.execute("UPDATE members SET role = 'admin' WHERE family_id = ? AND user_id = ?", (g.family_id, others[0]['user_id']))
        # Whoever leaves their only family gets a new, empty one
        if uid == g.user['id'] and len(g.families) == 1:
            family_id = db.create_family(conn, i18n.tr("{name}'s family", name=g.user['name']), g.user['language'])
            conn.execute("INSERT INTO members (family_id, user_id, role) VALUES (?, ?, 'admin')", (family_id, uid))
            db.ensure_person(conn, family_id, uid, g.user['name'])
            session['family_id'] = family_id
    return jsonify(ok=True)


# ---------- Invitations (public: they can be opened without an account) ----------

@bp.get('/invites/<token>')
def invite_info(token):
    rate_limit(f'invite-info:{token[:12]}', 30, 3600)
    with db.transaction() as conn:
        t = read_token(conn, token, 'invite')
        if not t:
            abort(404, 'Invalid or expired invitation')
        f = conn.execute('SELECT name FROM families WHERE id = ?', (t['family_id'],)).fetchone()
        sender = conn.execute('SELECT name FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    already_member = any(x['id'] == t['family_id'] for x in getattr(g, 'families', []) or [])
    return jsonify(family=f['name'], invited_by=sender['name'] if sender else None, already_member=already_member)


@bp.post('/invites/<token>/accept')
def accept_invite(token):
    hub.guard()
    if not getattr(g, 'user', None):
        abort(401, 'Sign in or sign up to accept')
    with db.transaction() as conn:
        t = read_token(conn, token, 'invite')
        if not t:
            abort(404, 'Invalid or expired invitation')
        conn.execute("INSERT OR IGNORE INTO members (family_id, user_id, role) VALUES (?, ?, 'member')",
                     (t['family_id'], g.user['id']))
        db.ensure_person(conn, t['family_id'], g.user['id'], g.user['name'])
        use_token(conn, token)
    session['family_id'] = t['family_id']
    return jsonify(ok=True)


# ---------- Other addresses I forward documents from (my account's email always works) ----------

@bp.post('/account/mail-senders')
def add_sender():
    from auth import EMAIL_RE
    email = text(body().get('email'), 254).lower()
    if not EMAIL_RE.match(email):
        abort(400, 'Invalid email')
    with db.transaction() as conn:
        if conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone() or \
                conn.execute('SELECT 1 FROM mail_senders WHERE email = ?', (email,)).fetchone():
            abort(409, 'This address is already in use')
        if conn.execute('SELECT COUNT(*) FROM mail_senders WHERE user_id = ?', (g.user['id'],)).fetchone()[0] >= 10:
            abort(400, 'Too many addresses')
        conn.execute('INSERT INTO mail_senders (user_id, email) VALUES (?, ?)', (g.user['id'], email))
    return jsonify(ok=True), 201


@bp.delete('/account/mail-senders/<path:email>')
def remove_sender(email):
    with db.transaction() as conn:
        conn.execute('DELETE FROM mail_senders WHERE user_id = ? AND email = ?', (g.user['id'], email.lower()))
    return jsonify(ok=True)

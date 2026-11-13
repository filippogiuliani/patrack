"""Authentication: users, sessions, single-use tokens and rate limiting."""
import datetime
import hashlib
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, abort, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import db
from famkit import hub
import i18n
from famkit import mail
from common import body, text

bp = Blueprint('auth', __name__)

# PATRACK_SIGNUP=closed: new accounts only through an invitation link.
SIGNUP_OPEN = os.environ.get('PATRACK_SIGNUP', 'open') != 'closed'
# PATRACK_PASSWORD_LOGIN=0: sign-in and sign-up only through the OIDC providers
PASSWORD_LOGIN = os.environ.get('PATRACK_PASSWORD_LOGIN', '1') not in ('0', 'off', 'false', 'no') and not hub.enabled()
BASE_URL = os.environ.get('PATRACK_URL', '').rstrip('/')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PASSWORD_MIN = 8
NO_PASSWORD = '!'  # account created through an external provider, without a password
# Dummy hash: the check runs even for unknown emails, so timing does not reveal who is registered
_DUMMY_HASH = generate_password_hash('dummy-password-for-constant-timing')

# Endpoints reachable without signing in
PUBLIC = {'/api/me', '/api/login', '/api/login/2fa', '/api/signup', '/api/forgot-password', '/api/reset-password', '/api/verify-email'}
# What an API token can't do: account, security, sign-in keys, membership
TOKEN_FORBIDDEN = ('/api/account', '/api/logout', '/api/family')
PUBLIC_PREFIXES = ('/api/invites/', '/api/oidc/', '/api/hub/')


# ---------- Rate limiting (in memory, per process) ----------
_attempts = defaultdict(deque)
_lock = threading.Lock()


def rate_limit(key, limit, window_s):
    """At most `limit` requests for `key` within `window_s` seconds, otherwise 429."""
    now = time.monotonic()
    with _lock:
        q = _attempts[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            abort(429, 'Too many attempts, try again in a few minutes')
        q.append(now)


def client_ip():
    return request.remote_addr or '?'


# ---------- Single-use tokens (only the hash is stored) ----------
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def create_token(conn, kind, hours, user_id=None, family_id=None):
    token = secrets.token_urlsafe(32)
    expires = (_utc_now() + datetime.timedelta(hours=hours)).isoformat(timespec='seconds')
    conn.execute('INSERT INTO tokens (hash, kind, user_id, family_id, expires_at) VALUES (?,?,?,?,?)',
                 (_hash(token), kind, user_id, family_id, expires))
    return token, expires


def read_token(conn, token, kind):
    """A valid (unused, unexpired) token row, or None."""
    if not token or len(token) > 100:
        return None
    r = conn.execute('SELECT * FROM tokens WHERE hash = ? AND kind = ?', (_hash(token), kind)).fetchone()
    if not r or r['used_at'] or r['expires_at'] < _utc_now().isoformat(timespec='seconds'):
        return None
    return r


def use_token(conn, token):
    conn.execute("UPDATE tokens SET used_at = datetime('now') WHERE hash = ?", (_hash(token),))


def app_link(path):
    """Absolute link to a frontend page (hash routing)."""
    return f"{BASE_URL or request.host_url.rstrip('/')}/#/{path}"


# ---------- Session ----------
def start_session(user, family_id=None):
    session.clear()
    session.permanent = True
    session['uid'] = user['id']
    session['ver'] = user['session_version']
    if family_id:
        session['family_id'] = family_id


def _token_user():
    """g.user etc. from an API token (Authorization: Bearer pt_…). The token is tied to one family."""
    token = request.headers.get('Authorization', '')[7:].strip()
    if not token.startswith('pt_') or len(token) > 100:
        return False
    with db.transaction() as conn:
        t = conn.execute('''SELECT t.id, t.family_id, t.last_used_at, m.role FROM api_tokens t
                            JOIN members m ON m.user_id = t.user_id AND m.family_id = t.family_id
                            WHERE t.hash = ?''', (_hash(token),)).fetchone()
        if not t:
            return False
        u = conn.execute('SELECT id, email, name, email_verified, session_version, language FROM users WHERE id = '
                         '(SELECT user_id FROM api_tokens WHERE id = ?)', (t['id'],)).fetchone()
        if not t['last_used_at'] or t['last_used_at'] < (_utc_now() - datetime.timedelta(hours=1)).isoformat(' ', 'seconds'):
            conn.execute("UPDATE api_tokens SET last_used_at = datetime('now') WHERE id = ?", (t['id'],))
        families = conn.execute('''SELECT f.id, f.name, m.role FROM members m JOIN families f ON f.id = m.family_id
                                   WHERE m.user_id = ? AND f.id = ?''', (u['id'], t['family_id'])).fetchall()
    g.user, g.families, g.family_id, g.role, g.via_token = dict(u), [dict(f) for f in families], t['family_id'], t['role'], True
    return True


def load_user():
    """Fill g.user / g.family_id / g.role from the session (or an API token). Returns False when not signed in."""
    if request.headers.get('Authorization', '').startswith('Bearer '):
        return _token_user()
    uid = session.get('uid')
    if not uid:
        return False
    with db.transaction() as conn:
        u = conn.execute('SELECT id, email, name, email_verified, session_version, language FROM users WHERE id = ?',
                         (uid,)).fetchone()
        if not u or u['session_version'] != session.get('ver'):
            session.clear()
            return False
        families = conn.execute('''SELECT f.id, f.name, m.role FROM members m JOIN families f ON f.id = m.family_id
                                   WHERE m.user_id = ? ORDER BY m.created_at''', (uid,)).fetchall()
    g.user = dict(u)
    g.families = [dict(f) for f in families]
    current = next((f for f in g.families if f['id'] == session.get('family_id')), g.families[0] if g.families else None)
    g.family_id = current['id'] if current else None
    g.role = current['role'] if current else None
    session['family_id'] = g.family_id
    return True


def require_login():
    """before_request: every API requires a signed-in user, except the public ones."""
    path = request.path
    if not path.startswith('/api/') or path in PUBLIC or path.startswith(PUBLIC_PREFIXES):
        if path.startswith('/api/'):
            load_user()
        return None
    if not load_user():
        return jsonify(error=i18n.tr('Sign-in required')), 401
    if getattr(g, 'via_token', False) and path.startswith(TOKEN_FORBIDDEN):
        return jsonify(error=i18n.tr('Not allowed with an API token')), 403
    if g.family_id is None and not path.startswith(('/api/account', '/api/logout')):
        return jsonify(error=i18n.tr('No family associated')), 403
    return None


def require_admin():
    if g.role != 'admin':
        abort(403, 'Only the family admin can do this')


# ---------- Validation ----------
def _email(value):
    e = text(value, 254).lower()
    if not EMAIL_RE.match(e):
        abort(400, 'Invalid email')
    return e


def _password(value):
    p = str(value or '')
    if len(p) < PASSWORD_MIN:
        abort(400, f'Password must be at least {PASSWORD_MIN} characters')
    if len(p) > 200:
        abort(400, 'Password too long')
    return p


def _send_verification(conn, user_id, email):
    token, _ = create_token(conn, 'verify', 72, user_id=user_id)
    lang = conn.execute('SELECT language FROM users WHERE id = ?', (user_id,)).fetchone()['language']
    mail.send(email, *i18n.email('verify', lang, link=app_link('verify/' + token)))


# ---------- Endpoints ----------
@bp.get('/me')
def me():
    from famkit import oidc
    base = {'signup_open': SIGNUP_OPEN and not hub.enabled(), 'oidc': oidc.public_providers(), 'password_login': PASSWORD_LOGIN,
            'hub': hub.public_info()}
    if not getattr(g, 'user', None):
        return jsonify(authenticated=False, **base)
    with db.transaction() as conn:
        password_hash, totp_on = conn.execute('SELECT password_hash, totp_secret IS NOT NULL FROM users WHERE id = ?',
                                              (g.user['id'],)).fetchone()
        identities = [r[0] for r in conn.execute('SELECT provider FROM identities WHERE user_id = ?', (g.user['id'],))]
        members = [dict(r) for r in conn.execute(
            'SELECT u.id, u.name FROM members m JOIN users u ON u.id = m.user_id WHERE m.family_id = ? ORDER BY m.created_at',
            (g.family_id,))]
        people = db.people(conn, g.family_id)
    family = next((f for f in g.families if f['id'] == g.family_id), None)
    user = {k: g.user[k] for k in ('id', 'email', 'name', 'email_verified', 'language')}
    user.update(has_password=password_hash != NO_PASSWORD, identities=identities, two_factor=bool(totp_on))
    import mailin
    return jsonify(authenticated=True, user=user, family=family, families=g.families, members=members, people=people,
                   role=g.role, inbox=mailin.ADDRESS or None, **base)


@bp.post('/signup')
def signup():
    if not PASSWORD_LOGIN:
        abort(403, 'Sign-up with a password is disabled: use one of the providers')
    rate_limit(f'signup:{client_ip()}', 10, 3600)
    d = body()
    name = text(d.get('name'), 80)
    if not name:
        abort(400, 'Name is required')
    email, password = _email(d.get('email')), _password(d.get('password'))
    if not d.get('consent'):
        abort(400, 'To sign up you must accept the privacy notice')
    with db.transaction() as conn:
        user, family_id = create_user(conn, name, email, generate_password_hash(password), False, d.get('invite'),
                                      d.get('language'))
    start_session(user, family_id)
    return jsonify(ok=True), 201


def create_user(conn, name, email, password_hash, email_verified, invite, language=None):
    """Create the user and put them in a family: the invitation's or a new one. Returns (user row, family id)."""
    if not SIGNUP_OPEN and not invite:
        abort(403, 'Sign-up is by invitation only')
    token = None
    if invite:
        token = read_token(conn, invite, 'invite')
        if not token:
            abort(400, 'Invalid or expired invitation')
    if conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
        abort(409, 'An account with this email already exists')
    lang = i18n.normalize(language) or i18n.language()
    uid = conn.execute("INSERT INTO users (email, name, password_hash, email_verified, language, consent_at) "
                       "VALUES (?,?,?,?,?,datetime('now'))",
                       (email, name, password_hash, 1 if email_verified else 0, lang)).lastrowid
    if token:
        family_id, role = token['family_id'], 'member'
        use_token(conn, invite)
    else:
        family_id = db.create_family(conn, i18n.tr("{name}'s family", lang, name=name), lang)
        role = 'admin'
    conn.execute('INSERT INTO members (family_id, user_id, role) VALUES (?,?,?)', (family_id, uid, role))
    db.ensure_person(conn, family_id, uid, name)
    if not email_verified:
        _send_verification(conn, uid, email)
    return conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone(), family_id


@bp.post('/login')
def login():
    """Email and password. With two-step verification on, the answer is {two_factor: true}: the code goes to /login/2fa."""
    if not PASSWORD_LOGIN:
        abort(403, 'Sign-in with a password is disabled: use one of the providers')
    d = body()
    email = text(d.get('email'), 254).lower()
    rate_limit(f'login-ip:{client_ip()}', 30, 900)
    rate_limit(f'login-email:{email}', 10, 900)
    with db.transaction() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not check_password_hash(u['password_hash'] if u else _DUMMY_HASH, str(d.get('password') or '')) or not u:
        abort(401, 'Wrong email or password')
    if u['totp_secret']:
        session.clear()
        session['pending_2fa'] = {'uid': u['id'], 'ver': u['session_version'], 'until': time.time() + 300}
        return jsonify(two_factor=True)
    start_session(u)
    return jsonify(ok=True)


@bp.post('/login/2fa')
def login_second_step():
    """The code from the authenticator app (or a recovery code), within 5 minutes of the password."""
    import security
    p = session.get('pending_2fa')
    if not p or p['until'] < time.time():
        session.pop('pending_2fa', None)
        abort(401, 'Sign-in expired: please enter your password again')
    rate_limit(f"login-2fa:{p['uid']}", 8, 900)
    with db.transaction() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (p['uid'],)).fetchone()
        if not u or u['session_version'] != p['ver'] or not security.second_factor_ok(conn, u, body().get('code')):
            abort(401, 'Wrong code')
    start_session(u)
    return jsonify(ok=True)


@bp.post('/logout')
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.post('/verify-email')
def verify_email():
    token = body().get('token')
    with db.transaction() as conn:
        t = read_token(conn, token, 'verify')
        if not t:
            abort(400, 'Invalid or expired link')
        conn.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (t['user_id'],))
        use_token(conn, token)
    return jsonify(ok=True)


@bp.post('/account/resend-verification')
def resend_verification():
    rate_limit(f'verify:{g.user["id"]}', 3, 3600)
    with db.transaction() as conn:
        _send_verification(conn, g.user['id'], g.user['email'])
    return jsonify(ok=True)


@bp.post('/forgot-password')
def forgot_password():
    email = text(body().get('email'), 254).lower()
    rate_limit(f'reset-ip:{client_ip()}', 10, 3600)
    rate_limit(f'reset-email:{email}', 3, 3600)
    with db.transaction() as conn:
        u = conn.execute('SELECT id, email, language FROM users WHERE email = ?', (email,)).fetchone()
        if u:
            token, _ = create_token(conn, 'reset', 2, user_id=u['id'])
            mail.send(u['email'], *i18n.email('reset', u['language'], link=app_link('reset/' + token)))
    # Same answer either way: we don't reveal which emails are registered
    return jsonify(ok=True)


@bp.post('/reset-password')
def reset_password():
    d = body()
    rate_limit(f'reset-use:{client_ip()}', 20, 3600)
    password = _password(d.get('password'))
    with db.transaction() as conn:
        t = read_token(conn, d.get('token'), 'reset')
        if not t:
            abort(400, 'Invalid or expired link')
        # New password: every open session is closed and the email counts as verified
        conn.execute('UPDATE users SET password_hash = ?, session_version = session_version + 1, email_verified = 1 WHERE id = ?',
                     (generate_password_hash(password), t['user_id']))
        use_token(conn, d.get('token'))
        u = conn.execute('SELECT * FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    start_session(u)
    return jsonify(ok=True)


@bp.put('/account')
def update_account():
    d = body()
    name = text(d.get('name', g.user['name']), 80)
    if not name:
        abort(400, 'Name is required')
    lang = i18n.normalize(d.get('language')) or g.user['language']
    with db.transaction() as conn:
        conn.execute('UPDATE users SET name = ?, language = ? WHERE id = ?', (name, lang, g.user['id']))
        conn.execute('UPDATE people SET name = ? WHERE user_id = ?', (name, g.user['id']))
    return jsonify(ok=True)


def _confirm_identity(conn, password, confirm_email=None):
    """Confirm it's really the user: with the password, or with the email when the account has none."""
    u = conn.execute('SELECT * FROM users WHERE id = ?', (g.user['id'],)).fetchone()
    rate_limit(f'pwd:{u["id"]}', 10, 900)
    if u['password_hash'] == NO_PASSWORD:
        if str(confirm_email or '').strip().lower() != u['email'].lower():
            abort(403, 'Type your email to confirm')
    elif not check_password_hash(u['password_hash'], str(password or '')):
        abort(403, 'Current password is wrong')
    return u


@bp.post('/account/password')
def change_password():
    d = body()
    new = _password(d.get('new'))
    with db.transaction() as conn:
        _confirm_identity(conn, d.get('current'), g.user['email'])  # accounts without a password can set one
        conn.execute('UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?',
                     (generate_password_hash(new), g.user['id']))
        u = conn.execute('SELECT * FROM users WHERE id = ?', (g.user['id'],)).fetchone()
    start_session(u, g.family_id)  # stay signed in here, close the other sessions
    return jsonify(ok=True)


@bp.delete('/account')
def delete_account():
    """Delete the account. Families where the user was the only member are deleted with all their data."""
    with db.transaction() as conn:
        d = body()
        _confirm_identity(conn, d.get('password'), d.get('confirm_email'))
        uid = g.user['id']
        for (family_id,) in conn.execute('SELECT family_id FROM members WHERE user_id = ?', (uid,)).fetchall():
            others = conn.execute('SELECT user_id, role FROM members WHERE family_id = ? AND user_id != ? ORDER BY created_at',
                                  (family_id, uid)).fetchall()
            if not others:
                conn.execute('DELETE FROM families WHERE id = ?', (family_id,))
            elif not any(o['role'] == 'admin' for o in others):
                conn.execute("UPDATE members SET role = 'admin' WHERE family_id = ? AND user_id = ?", (family_id, others[0]['user_id']))
        conn.execute('DELETE FROM users WHERE id = ?', (uid,))
    session.clear()
    return jsonify(ok=True)

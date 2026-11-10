"""Account security and integrations.

- Two-step verification (TOTP, RFC 6238) with single-use recovery codes. It applies to password sign-in;
  external providers (OIDC) have their own, and API tokens are separate revocable keys.
- "Sign out everywhere else".
- Personal API tokens (Authorization: Bearer pt_…) for the iPhone Shortcut and scripts."""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

from flask import Blueprint, abort, g, jsonify, session
from werkzeug.security import check_password_hash

import db
from auth import NO_PASSWORD, rate_limit, start_session
from common import body, text

bp = Blueprint('security', __name__)

ISSUER = 'paTrack'
RECOVERY_CODES = 10


# ======================================================================
# TOTP
# ======================================================================

def totp(secret, at=None, step=30, digits=6):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // step)
    h = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


_last_used = {}  # user id -> time step of the last accepted code (a code works once)


def check_totp(user_id, secret, code, at=None):
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != 6 or not secret:
        return False
    now = time.time() if at is None else at
    for drift in (0, -1, 1):  # the phone's clock may be 30 s off
        t = now + drift * 30
        if hmac.compare_digest(totp(secret, t), code):
            step = int(t // 30)
            if _last_used.get(user_id, -1) >= step:
                return False
            _last_used[user_id] = step
            return True
    return False


def _hash(code):
    return hashlib.sha256(code.replace('-', '').replace(' ', '').lower().encode()).hexdigest()


def use_recovery_code(conn, user_id, code):
    r = conn.execute('SELECT hash FROM recovery_codes WHERE user_id = ? AND hash = ? AND used_at IS NULL',
                     (user_id, _hash(str(code or '')))).fetchone()
    if not r:
        return False
    conn.execute("UPDATE recovery_codes SET used_at = datetime('now') WHERE user_id = ? AND hash = ?", (user_id, r['hash']))
    return True


def second_factor_ok(conn, user, code):
    """A TOTP code or an unused recovery code."""
    return check_totp(user['id'], user['totp_secret'], code) or use_recovery_code(conn, user['id'], code)


def _new_recovery_codes(conn, user_id):
    conn.execute('DELETE FROM recovery_codes WHERE user_id = ?', (user_id,))
    codes = []
    for _ in range(RECOVERY_CODES):
        c = secrets.token_hex(4)
        c = f'{c[:4]}-{c[4:]}'
        conn.execute('INSERT INTO recovery_codes (user_id, hash) VALUES (?,?)', (user_id, _hash(c)))
        codes.append(c)
    return codes


def _qr_svg(uri):
    import segno
    out = io.BytesIO()
    segno.make(uri, error='m').save(out, kind='svg', scale=5, border=2, dark='#111827', light='#ffffff', xmldecl=False)
    return 'data:image/svg+xml;base64,' + base64.b64encode(out.getvalue()).decode()


def _status(conn):
    left = conn.execute('SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND used_at IS NULL', (g.user['id'],)).fetchone()[0]
    on = bool(conn.execute('SELECT totp_secret FROM users WHERE id = ?', (g.user['id'],)).fetchone()[0])
    return {'enabled': on, 'recovery_left': left if on else 0}


@bp.get('/account/2fa')
def status():
    with db.transaction() as conn:
        return jsonify(_status(conn))


@bp.post('/account/2fa/setup')
def setup():
    """A new secret to add to the authenticator app; it becomes active once a code is confirmed."""
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
    with db.transaction() as conn:
        conn.execute('UPDATE users SET totp_pending = ? WHERE id = ?', (secret, g.user['id']))
    uri = f"otpauth://totp/{quote(ISSUER)}:{quote(g.user['email'])}?secret={secret}&issuer={quote(ISSUER)}&digits=6&period=30"
    return jsonify(secret=' '.join(secret[i:i + 4] for i in range(0, len(secret), 4)), uri=uri, qr=_qr_svg(uri))


@bp.post('/account/2fa/enable')
def enable():
    rate_limit(f"2fa-setup:{g.user['id']}", 10, 900)
    code = body().get('code')
    with db.transaction() as conn:
        pending = conn.execute('SELECT totp_pending FROM users WHERE id = ?', (g.user['id'],)).fetchone()[0]
        if not pending:
            abort(400, 'Start the setup again')
        if not check_totp(g.user['id'], pending, code):
            abort(400, 'Wrong code: check the time on your phone and try again')
        conn.execute('UPDATE users SET totp_secret = ?, totp_pending = NULL WHERE id = ?', (pending, g.user['id']))
        codes = _new_recovery_codes(conn, g.user['id'])
        return jsonify(**_status(conn), recovery_codes=codes)


def _confirm_identity(conn, d):
    """Turning 2FA off or new recovery codes: a current code (or recovery code) or the password."""
    rate_limit(f"2fa-confirm:{g.user['id']}", 10, 900)
    u = conn.execute('SELECT * FROM users WHERE id = ?', (g.user['id'],)).fetchone()
    if d.get('code') and second_factor_ok(conn, u, d['code']):
        return
    if d.get('password') and u['password_hash'] != NO_PASSWORD and check_password_hash(u['password_hash'], str(d['password'])):
        return
    abort(400, 'Wrong code or password')


@bp.post('/account/2fa/disable')
def disable():
    d = body()
    with db.transaction() as conn:
        _confirm_identity(conn, d)
        conn.execute('UPDATE users SET totp_secret = NULL, totp_pending = NULL WHERE id = ?', (g.user['id'],))
        conn.execute('DELETE FROM recovery_codes WHERE user_id = ?', (g.user['id'],))
        return jsonify(_status(conn))


@bp.post('/account/2fa/recovery-codes')
def regenerate():
    d = body()
    with db.transaction() as conn:
        if not _status(conn)['enabled']:
            abort(400, 'Two-step verification is off')
        _confirm_identity(conn, d)
        codes = _new_recovery_codes(conn, g.user['id'])
        return jsonify(**_status(conn), recovery_codes=codes)


@bp.post('/account/sessions/revoke')
def revoke_sessions():
    """Sign out on every other device (this one stays signed in)."""
    with db.transaction() as conn:
        conn.execute('UPDATE users SET session_version = session_version + 1 WHERE id = ?', (g.user['id'],))
        user = conn.execute('SELECT * FROM users WHERE id = ?', (g.user['id'],)).fetchone()
    start_session(user, g.family_id)
    return jsonify(ok=True)


# ======================================================================
# API tokens
# ======================================================================

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@bp.get('/account/tokens')
def tokens():
    with db.transaction() as conn:
        return jsonify([dict(r) for r in conn.execute(
            'SELECT id, name, hint, last_used_at, created_at FROM api_tokens WHERE user_id = ? AND family_id = ? ORDER BY id',
            (g.user['id'], g.family_id))])


@bp.post('/account/tokens')
def create_token():
    """A token for the current family, shown only now."""
    name = text(body().get('name'), 60) or 'API'
    token = 'pt_' + secrets.token_urlsafe(32)
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM api_tokens WHERE user_id = ?', (g.user['id'],)).fetchone()[0] >= 20:
            abort(400, 'Too many tokens')
        conn.execute('INSERT INTO api_tokens (user_id, family_id, name, hash, hint) VALUES (?,?,?,?,?)',
                     (g.user['id'], g.family_id, name, token_hash(token), token[:6] + '…' + token[-4:]))
    return jsonify(token=token, name=name), 201


@bp.delete('/account/tokens/<int:tid>')
def delete_token(tid):
    with db.transaction() as conn:
        conn.execute('DELETE FROM api_tokens WHERE id = ? AND user_id = ?', (tid, g.user['id']))
    return tokens()



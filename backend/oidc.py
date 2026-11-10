"""Sign-in with external OpenID Connect providers (Google or any OIDC provider).

Configuration (environment variables):
  PATRACK_OIDC=google,company                  enabled providers
  PATRACK_OIDC_GOOGLE_ID / _SECRET             client credentials
  PATRACK_OIDC_COMPANY_ISSUER                  issuer URL (Google already has a default)
  PATRACK_OIDC_COMPANY_NAME                    name shown on the button (optional)
Callback URL to register with the provider:  <PATRACK_URL>/api/oidc/<provider>/callback
"""
import os
from urllib.parse import quote

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, g, jsonify, redirect, request, session

import db
import hub
import i18n
from auth import BASE_URL, NO_PASSWORD, create_user, rate_limit, start_session
from common import body, text

bp = Blueprint('oidc', __name__)
oauth = OAuth()

DEFAULTS = {
    'google': {'issuer': 'https://accounts.google.com', 'name': 'Google'},
}
PROVIDERS = {}  # id -> display name


def configure(app):
    oauth.init_app(app)
    for pid in [p.strip().lower() for p in os.environ.get('PATRACK_OIDC', '').split(',') if p.strip()]:
        env = lambda k: os.environ.get(f'PATRACK_OIDC_{pid.upper()}_{k}', '')
        issuer = (env('ISSUER') or DEFAULTS.get(pid, {}).get('issuer', '')).rstrip('/')
        if not (env('ID') and env('SECRET') and issuer):
            print(f'[oidc] provider "{pid}" ignored: ID, SECRET or ISSUER missing', flush=True)
            continue
        oauth.register(
            pid, client_id=env('ID'), client_secret=env('SECRET'),
            server_metadata_url=f'{issuer}/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
        )
        PROVIDERS[pid] = env('NAME') or DEFAULTS.get(pid, {}).get('name') or pid.capitalize()
        print(f'[oidc] provider enabled: {pid}', flush=True)


def public_providers():
    return [{'id': k, 'name': v} for k, v in PROVIDERS.items()]


def _client(pid):
    if pid not in PROVIDERS:
        abort(404, 'Provider not configured')
    return oauth.create_client(pid)


def _frontend(path=''):
    return redirect(f"{BASE_URL or request.host_url.rstrip('/')}/#/{path}")


def _error(message):
    return _frontend('login?error=' + quote(i18n.tr(message)))


@bp.get('/oidc/<pid>/login')
def start(pid):
    client = _client(pid)
    rate_limit(f'oidc:{request.remote_addr}', 30, 900)
    session['oidc_flow'] = {'invite': request.args.get('invite') or None, 'link': request.args.get('link') == '1'}
    callback_url = f"{BASE_URL or request.host_url.rstrip('/')}/api/oidc/{pid}/callback"
    return client.authorize_redirect(callback_url)


@bp.get('/oidc/<pid>/callback')
def callback(pid):
    client = _client(pid)
    flow = session.pop('oidc_flow', None) or {}
    try:
        token = client.authorize_access_token()  # checks state, PKCE, id_token signature and nonce
    except Exception as e:
        print(f'[oidc] {pid}: sign-in failed: {e}', flush=True)
        return _error('Sign-in failed, please try again')
    info = token.get('userinfo') or {}
    subject, email = str(info.get('sub') or ''), str(info.get('email') or '').lower()
    verified = info.get('email_verified') in (True, 'true')
    if not subject:
        return _error('The provider did not return an identifier')

    if hub.enabled():
        # The family lives in weHub: it says who this is and what they may use
        try:
            user = hub.sign_in(pid, str(info.get('iss') or ''), subject, email, verified,
                               text(info.get('name') or email.split('@')[0], 80))
        except hub.NoAccess:
            return _error('You cannot use this app: ask the family admin in weHub')
        except hub.Unavailable as e:
            print(f'[hub] sign-in: {e}', flush=True)
            return _error('weHub is not reachable, please try again in a moment')
        with db.transaction() as conn:
            conn.execute('INSERT OR IGNORE INTO identities (provider, subject, user_id, email) VALUES (?,?,?,?)',
                         (pid, subject, user['id'], email))
            conn.execute('UPDATE identities SET user_id = ? WHERE provider = ? AND subject = ?', (user['id'], pid, subject))
        start_session(user)
        return _frontend('')

    with db.transaction() as conn:
        linked = conn.execute('SELECT user_id FROM identities WHERE provider = ? AND subject = ?', (pid, subject)).fetchone()

        # Linking to an account that is already signed in (from the Family page)
        if flow.get('link') and getattr(g, 'user', None):
            if linked and linked['user_id'] != g.user['id']:
                return _frontend('family?error=' + quote(i18n.tr('This account is already linked to another user')))
            conn.execute('INSERT OR IGNORE INTO identities (provider, subject, user_id, email) VALUES (?,?,?,?)',
                         (pid, subject, g.user['id'], email))
            return _frontend('family')

        if linked:
            user = conn.execute('SELECT * FROM users WHERE id = ?', (linked['user_id'],)).fetchone()
        elif email and verified and (user := conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()):
            # Same email, verified by the provider: link the identity to the existing account
            conn.execute('INSERT INTO identities (provider, subject, user_id, email) VALUES (?,?,?,?)', (pid, subject, user['id'], email))
            if not user['email_verified']:
                conn.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (user['id'],))
        else:
            if not email or not verified:
                return _error('The provider did not return a verified email address')
            # New user: consent to the privacy notice is needed before creating the account
            session['oidc_pending'] = {'provider': pid, 'subject': subject, 'email': email,
                                       'name': text(info.get('name') or info.get('given_name') or email.split('@')[0], 80),
                                       'invite': flow.get('invite')}
            return _frontend('signup?external=1')

    start_session(user)
    if flow.get('invite'):
        return _frontend('invite/' + quote(flow['invite']))
    return _frontend('')


@bp.get('/oidc/pending')
def pending():
    """Data of the new user waiting to complete sign-up."""
    p = session.get('oidc_pending')
    if not p:
        abort(404, 'No sign-up in progress')
    return jsonify(email=p['email'], name=p['name'], provider=PROVIDERS.get(p['provider'], p['provider']),
                   invite=bool(p.get('invite')))


@bp.post('/oidc/complete')
def complete():
    p = session.get('oidc_pending')
    if not p:
        abort(400, 'Sign-up expired: please try again')
    d = body()
    if not d.get('consent'):
        abort(400, 'To sign up you must accept the privacy notice')
    with db.transaction() as conn:
        user, family_id = create_user(conn, text(d.get('name'), 80) or p['name'], p['email'], NO_PASSWORD, True,
                                      p.get('invite'), d.get('language'))
        conn.execute('INSERT INTO identities (provider, subject, user_id, email) VALUES (?,?,?,?)',
                     (p['provider'], p['subject'], user['id'], p['email']))
    start_session(user, family_id)
    return jsonify(ok=True), 201


@bp.delete('/account/identities/<pid>')
def unlink(pid):
    """Unlink a provider, as long as another way to sign in remains."""
    with db.transaction() as conn:
        password_hash = conn.execute('SELECT password_hash FROM users WHERE id = ?', (g.user['id'],)).fetchone()[0]
        others = conn.execute('SELECT COUNT(*) FROM identities WHERE user_id = ? AND provider != ?', (g.user['id'], pid)).fetchone()[0]
        if password_hash == NO_PASSWORD and not others:
            abort(400, "Set a password first, otherwise you couldn't sign in anymore")
        conn.execute('DELETE FROM identities WHERE user_id = ? AND provider = ?', (g.user['id'], pid))
    return jsonify(ok=True)

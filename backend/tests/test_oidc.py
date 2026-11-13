"""Sign-in through OIDC providers (Google or others), with a fake provider instead of a real one."""
import pytest
from flask import abort, redirect

import auth
from famkit import oidc
from conftest import PASSWORD, ok, sign_up


class FakeProvider:
    """Replaces the Authlib client: `user` is what the provider returns on the next callback."""
    user = None

    def authorize_redirect(self, callback_url):
        return redirect('https://idp.example/auth?redirect_uri=' + callback_url)

    def authorize_access_token(self):
        if self.user is None:
            raise ValueError('invalid state')
        return {'userinfo': self.user}


@pytest.fixture
def idp(app, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(oidc, 'PROVIDERS', {'fake': 'Test provider'})

    def client(pid):
        if pid not in oidc.PROVIDERS:
            abort(404, 'Provider not configured')
        return fake
    monkeypatch.setattr(oidc, '_client', client)
    return fake


def sign_in(c, idp, sub, email, verified=True, query=''):
    """Go through login → provider → callback and return the frontend page it lands on."""
    r = c.get('/api/oidc/fake/login' + query)
    assert r.status_code == 302 and r.headers['Location'].startswith('https://idp.example/')
    idp.user = {'sub': sub, 'email': email, 'email_verified': verified, 'name': 'Provider Name'}
    r = c.get('/api/oidc/fake/callback?code=x&state=y')
    assert r.status_code == 302
    return r.headers['Location'].split('#/', 1)[1]


def test_providers_listed_in_me(client, idp):
    assert ok(client().get('/api/me'))['oidc'] == [{'id': 'fake', 'name': 'Test provider'}]
    assert client().get('/api/oidc/unknown/login').status_code == 404


def test_new_user_must_accept_privacy_notice(client, idp):
    c = client()
    assert sign_in(c, idp, 'sub-1', 'new@example.com') == 'signup?external=1'
    assert ok(c.get('/api/me'))['authenticated'] is False
    assert ok(c.get('/api/oidc/pending'))['email'] == 'new@example.com'
    assert c.post('/api/oidc/complete', json={}).status_code == 400
    ok(c.post('/api/oidc/complete', json={'consent': True}), 201)
    me = ok(c.get('/api/me'))
    assert me['user']['email'] == 'new@example.com' and me['user']['has_password'] is False
    assert me['user']['email_verified'] and me['family']['role'] == 'admin'
    # Next time they go straight in
    assert sign_in(client(), idp, 'sub-1', 'new@example.com') == ''


def test_links_existing_account_with_same_email(client, idp):
    sign_up(client())
    c = client()
    assert sign_in(c, idp, 'sub-2', 'fil@example.com') == ''
    me = ok(c.get('/api/me'))
    assert me['user']['email'] == 'fil@example.com' and 'fake' in me['user']['identities']


def test_unverified_email_is_rejected(client, idp):
    c = client()
    assert sign_in(c, idp, 'sub-3', 'x@example.com', verified=False).startswith('login?error=')
    assert ok(c.get('/api/me'))['authenticated'] is False


def test_invalid_callback(client, idp):
    c = client()
    c.get('/api/oidc/fake/login')
    idp.user = None
    assert c.get('/api/oidc/fake/callback?code=x&state=bad').headers['Location'].split('#/', 1)[1].startswith('login?error=')
    assert ok(c.get('/api/me'))['authenticated'] is False


def test_closed_sign_up_blocks_new_oidc_users(client, idp, monkeypatch):
    """With PATRACK_SIGNUP=closed an unknown external account cannot create a user."""
    sign_up(client())
    monkeypatch.setattr(auth, 'SIGNUP_OPEN', False)
    stranger = client()
    sign_in(stranger, idp, 'sub-x', 'stranger@example.com')
    assert stranger.post('/api/oidc/complete', json={'consent': True}).status_code == 403
    assert ok(stranger.get('/api/me'))['authenticated'] is False
    # Whoever already has an account (same verified email) still gets in
    assert sign_in(client(), idp, 'sub-fil', 'fil@example.com') == ''


def test_unlinking_the_only_sign_in_requires_a_password(client, idp):
    c = client()
    sign_in(c, idp, 'sub-4', 'only@example.com')
    ok(c.post('/api/oidc/complete', json={'consent': True}), 201)
    assert c.delete('/api/account/identities/fake').status_code == 400
    ok(c.post('/api/account/password', json={'new': PASSWORD}))
    ok(c.delete('/api/account/identities/fake'))
    ok(client().post('/api/login', json={'email': 'only@example.com', 'password': PASSWORD}))

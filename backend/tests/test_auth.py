"""Sign-up, sign-in, email verification, password recovery and protections."""
import auth
from conftest import PASSWORD, emailed_token, invite_token, ok, sign_up


def test_api_requires_sign_in(client):
    c = client()
    assert c.get('/api/documents').status_code == 401
    assert ok(c.get('/api/me'))['authenticated'] is False


def test_sign_up_validates_input(client):
    c = client()
    base = {'name': 'X', 'email': 'x@example.com', 'password': PASSWORD, 'consent': True}
    assert c.post('/api/signup', json={**base, 'password': 'short'}).status_code == 400
    assert c.post('/api/signup', json={**base, 'email': 'not-an-email'}).status_code == 400
    assert c.post('/api/signup', json={**base, 'consent': False}).status_code == 400
    assert c.post('/api/signup', json={**base, 'name': ''}).status_code == 400
    ok(c.post('/api/signup', json=base), 201)
    assert client().post('/api/signup', json=base).status_code == 409


def test_sign_up_creates_family_admin(client):
    me = sign_up(client())
    assert me['authenticated'] and me['family']['role'] == 'admin'
    assert [m['name'] for m in me['members']] == ['Fil']
    assert not me['user']['email_verified']


def test_login(client):
    sign_up(client())
    c = client()
    assert c.post('/api/login', json={'email': 'fil@example.com', 'password': 'wrong'}).status_code == 401
    assert c.post('/api/login', json={'email': 'nobody@example.com', 'password': PASSWORD}).status_code == 401
    ok(c.post('/api/login', json={'email': 'FIL@example.com', 'password': PASSWORD}))  # email is case-insensitive
    assert ok(c.get('/api/me'))['authenticated']
    ok(c.post('/api/logout'))
    assert ok(c.get('/api/me'))['authenticated'] is False


def test_email_verification_is_single_use(client, outbox):
    c = client()
    sign_up(c)
    token = emailed_token(outbox, 'fil@example.com', 'verify')
    assert token
    ok(c.post('/api/verify-email', json={'token': token}))
    assert ok(c.get('/api/me'))['user']['email_verified']
    assert c.post('/api/verify-email', json={'token': token}).status_code == 400


def test_password_reset_closes_other_sessions(client, outbox):
    old = client()
    sign_up(old)
    anon = client()
    ok(anon.post('/api/forgot-password', json={'email': 'fil@example.com'}))
    ok(anon.post('/api/forgot-password', json={'email': 'nobody@example.com'}))  # does not reveal who is registered
    token = emailed_token(outbox, 'fil@example.com', 'reset')
    ok(anon.post('/api/reset-password', json={'token': token, 'password': 'newpass123'}))
    assert ok(old.get('/api/me'))['authenticated'] is False
    assert client().post('/api/login', json={'email': 'fil@example.com', 'password': PASSWORD}).status_code == 401
    ok(client().post('/api/login', json={'email': 'fil@example.com', 'password': 'newpass123'}))
    assert anon.post('/api/reset-password', json={'token': token, 'password': 'another123'}).status_code == 400


def test_change_password(client):
    c = client()
    sign_up(c)
    assert c.post('/api/account/password', json={'current': 'wrong', 'new': 'newpass123'}).status_code == 403
    ok(c.post('/api/account/password', json={'current': PASSWORD, 'new': 'newpass123'}))
    ok(client().post('/api/login', json={'email': 'fil@example.com', 'password': 'newpass123'}))


def test_login_rate_limit(client):
    sign_up(client())
    c = client()
    codes = [c.post('/api/login', json={'email': 'fil@example.com', 'password': 'x'}).status_code for _ in range(12)]
    assert 429 in codes


def test_csrf_foreign_origin_is_blocked(client):
    c = client()
    sign_up(c)
    assert c.post('/api/logout', headers={'Origin': 'https://evil.example'}).status_code == 403
    ok(c.post('/api/logout', headers={'Origin': 'http://localhost'}))


def test_closed_sign_up_requires_invitation(client, monkeypatch):
    admin = client()
    sign_up(admin)
    monkeypatch.setattr(auth, 'SIGNUP_OPEN', False)
    assert ok(client().get('/api/me'))['signup_open'] is False
    base = {'name': 'X', 'email': 'x@example.com', 'password': PASSWORD, 'consent': True}
    assert client().post('/api/signup', json=base).status_code == 403
    new = client()
    ok(new.post('/api/signup', json={**base, 'invite': invite_token(admin)}), 201)
    assert ok(new.get('/api/me'))['family']['role'] == 'member'


def test_delete_account(client):
    c = client()
    sign_up(c)
    assert c.delete('/api/account', json={'password': 'wrong'}).status_code == 403
    ok(c.delete('/api/account', json={'password': PASSWORD}))
    assert client().post('/api/login', json={'email': 'fil@example.com', 'password': PASSWORD}).status_code == 401


def test_messages_follow_the_language(client):
    c = client()
    r = c.post('/api/signup', json={'name': 'J', 'email': 'j@example.com', 'password': 'short', 'consent': True},
               headers={'Accept-Language': 'en-US,en;q=0.9'})
    assert r.status_code == 400 and r.get_json()['error'] == 'Password must be at least 8 characters'
    sign_up(c, email='j@example.com', language='en')
    assert c.get('/api/documents/999999').get_json()['error'] == 'Document not found'
    ok(c.put('/api/account', json={'language': 'it'}))
    assert c.get('/api/documents/999999').get_json()['error'] == 'Documento non trovato'
    # Field names inside messages are translated too
    assert c.put('/api/family/people/1', json={'name': 'X', 'birth_date': 'ieri'}).get_json()['error'] == \
        'data di nascita: data non valida'


def test_default_language_is_italian(client):
    r = client().post('/api/signup', json={'name': 'X', 'email': 'x@example.com', 'password': 'short', 'consent': True})
    assert r.get_json()['error'] == 'La password deve avere almeno 8 caratteri'
    c = client()
    sign_up(c, email='nolang@example.com')
    assert ok(c.get('/api/me'))['user']['language'] == 'it'


def test_account_name_is_also_the_person_name(client):
    c = client()
    sign_up(c)
    ok(c.put('/api/account', json={'name': 'Marco'}))
    me = ok(c.get('/api/me'))
    assert me['user']['name'] == 'Marco' and me['people'][0]['name'] == 'Marco'

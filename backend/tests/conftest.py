"""Shared fixtures: every test gets a fresh database in a temporary directory, emails are captured
instead of being sent and rate limits start from zero."""
import os
import re
import sys
import tempfile

# Modules read PATRACK_DATA on import: point it at a throwaway directory right away,
# so no test can ever touch backend/data or a real data directory.
os.environ['PATRACK_DATA'] = tempfile.mkdtemp(prefix='patrack-test-')
for k in [k for k in os.environ if k.startswith('PATRACK_') and k != 'PATRACK_DATA']:
    del os.environ[k]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import auth  # noqa: E402
import backup  # noqa: E402
import db  # noqa: E402
import mail  # noqa: E402
import oidc  # noqa: E402
import storage  # noqa: E402
from app import create_app  # noqa: E402

PASSWORD = 'secret123'


@pytest.fixture
def outbox(monkeypatch):
    """Emails "sent" during the test: list of (to, subject, body)."""
    sent = []
    monkeypatch.setattr(mail, 'send', lambda to, subject, body: sent.append((to, subject, body)))
    return sent


@pytest.fixture
def app(tmp_path, monkeypatch, outbox):
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'patrack.db'))
    monkeypatch.setattr(backup, 'BACKUP_DIR', str(tmp_path / 'backups'))
    storage.reset_key_cache()
    import mailin
    mailin._status.update(last_check=None, last_ok=None, last_error=None, imported=0)
    monkeypatch.setattr(auth, 'SIGNUP_OPEN', True)
    monkeypatch.setattr(oidc, 'PROVIDERS', {})
    auth._attempts.clear()
    import security
    security._last_used.clear()
    return create_app()


def run_queue():
    """Process the whole import queue now (the background worker is not running in tests)."""
    import imports
    while imports.process_one():
        pass


@pytest.fixture
def client(app):
    return app.test_client


def ok(r, code=200):
    """Check the status code and return the JSON body."""
    assert r.status_code == code, (r.status_code, r.get_data(as_text=True)[:500])
    return r.get_json()


def sign_up(c, email='fil@example.com', name='Fil', **extra):
    """Sign up with client `c` (which stays signed in) and return /api/me."""
    ok(c.post('/api/signup', json={'name': name, 'email': email, 'password': PASSWORD, 'consent': True, **extra}), 201)
    return ok(c.get('/api/me'))


def emailed_token(outbox, to, kind):
    """Token of the latest #/<kind>/<token> link sent to `to`."""
    for dest, _, body in reversed(outbox):
        if dest == to and (m := re.search(r'#/' + kind + r'/(\S+)', body)):
            return m.group(1)
    return None


def invite_token(c):
    return ok(c.post('/api/family/invites'), 201)['link'].split('#/invite/')[1]


class Family:
    """An admin ("Fil") and, after `add_partner()`, a second member ("Sara") sharing the family."""

    def __init__(self, client):
        self.client = client
        self.c = client()
        self.me = sign_up(self.c, language='it')
        self.uid = self.me['user']['id']

    def add_partner(self):
        self.p = self.client()
        ok(self.p.post('/api/signup', json={'name': 'Sara', 'email': 'sara@example.com', 'password': PASSWORD,
                                            'consent': True, 'invite': invite_token(self.c)}), 201)
        self.puid = ok(self.p.get('/api/me'))['user']['id']
        return self.p

    def upload(self, data, name='doc.pdf', c=None, process=True, **form):
        """Upload a file through the API and (by default) process the queue; returns the import row."""
        import io
        r = ok((c or self.c).post('/api/imports', data={'file': (io.BytesIO(data), name), **form},
                                  content_type='multipart/form-data'), 201)
        if process:
            run_queue()
            r = ok((c or self.c).get(f"/api/imports/{r['id']}"))
        return r


@pytest.fixture
def family(client):
    return Family(client)

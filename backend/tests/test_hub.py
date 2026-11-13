"""weHub mode for paTrack: members and people come from weHub (simulated here); documents keep their person."""
import pytest
from flask import redirect

import auth
import db
from famkit import hub
from famkit import oidc
from conftest import PASSWORD, ok, sign_up
from samples import pdf_with_text

KEY = 'k' * 40


class FakeHub:
    """Stands in for weHub's service API."""

    def __init__(self):
        self.users = {}       # (issuer, subject) or email → user
        self.families = {}    # hub id → snapshot
        self.access = {}      # user hub id → [family hub ids]
        self.down = False

    def __call__(self, method, path, payload=None):
        if self.down:
            raise hub.Unavailable('down')
        if path == '/whoami':
            u = self.users.get(payload['email'])
            if not u:
                return {'known': False}
            return {'known': True, 'user': u, 'families': [self.families[f] for f in self.access.get(u['hub_id'], [])]}
        fid = int(path.split('/')[2].split('?')[0])
        snap = self.families.get(fid)
        if snap and f"version={snap['version']}" in path:
            return {'unchanged': True}
        return snap


class FakeProvider:
    user = None

    def authorize_redirect(self, url):
        return redirect('https://id.example/auth')

    def authorize_access_token(self):
        return {'userinfo': self.user}


@pytest.fixture
def wehub(app, monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hub, 'URL', 'http://wehub.test')
    monkeypatch.setattr(hub, 'KEY', KEY)
    monkeypatch.setattr(hub, '_call', fake)
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', False)
    provider = FakeProvider()
    monkeypatch.setattr(oidc, 'PROVIDERS', {'pocketid': 'Pocket ID'})
    monkeypatch.setattr(oidc, '_client', lambda pid: provider)
    fake.provider = provider
    return fake


def user(hub_id, name, email):
    return {'hub_id': hub_id, 'name': name, 'email': email, 'language': 'it'}


def family(fake, hub_id=1, version=1, members=(), people=(), local_id=None, name='Casa'):
    fake.families[hub_id] = {'hub_id': hub_id, 'name': name, 'version': version, 'local_id': local_id,
                             'members': [{**m, 'role': m.get('role', 'member'), 'level': 'full'} for m in members],
                             'people': list(people)}


def sign_in(c, fake, email, sub=None):
    c.get('/api/oidc/pocketid/login')
    fake.provider.user = {'sub': sub or email, 'email': email, 'email_verified': True, 'name': 'X', 'iss': 'https://id.example'}
    r = c.get('/api/oidc/pocketid/callback?code=x&state=y')
    assert r.status_code == 302
    return r.headers['Location'].split('#/', 1)[1]


def test_sign_in_creates_family_and_people(client, wehub):
    fil, sara = user(10, 'Fil', 'fil@example.com'), user(11, 'Sara', 'sara@example.com')
    wehub.users = {'fil@example.com': fil, 'sara@example.com': sara}
    family(wehub, members=[{**fil, 'role': 'admin'}],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}, {'hub_id': 101, 'name': 'Sara', 'user_hub_id': 11},
                   {'hub_id': 102, 'name': 'Luca', 'kind': 'child', 'birth_date': '2025-01-10', 'user_hub_id': None}])
    wehub.access = {10: [1]}
    c = client()
    assert sign_in(c, wehub, 'fil@example.com') == ''
    me = ok(c.get('/api/me'))
    people = {p['name']: p for p in me['people']}
    assert set(people) == {'Fil', 'Sara', 'Luca'}
    assert people['Fil']['user_id'] == me['user']['id'] and people['Sara']['user_id'] is None   # Sara: no paTrack access
    assert people['Luca']['birth_date'] == '2025-01-10'
    assert me['hub']['name'] == 'weHub' and me['password_login'] is False
    assert c.post('/api/family/people', json={'name': 'X'}).status_code == 409
    assert c.post('/api/family/invites').status_code == 409
    # The iPhone key keeps working in weHub mode
    t = ok(c.post('/api/account/tokens', json={'name': 'iPhone'}), 201)['token']
    assert client().get('/api/documents', headers={'Authorization': 'Bearer ' + t}).status_code == 200


def test_existing_people_and_documents_are_kept(client, wehub, monkeypatch):
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    from conftest import Family
    f = Family(client)
    people = ok(f.c.post('/api/family/people', json={'name': 'Luca'}), 201)
    luca = next(p['id'] for p in people if p['name'] == 'Luca')
    me_person = f.me['people'][0]['id']
    doc_luca = f.upload(pdf_with_text(['Referto di Luca']), person_id=str(luca))['document_id']
    doc_me = f.upload(pdf_with_text(['Busta paga di Fil']), 'b.pdf', person_id=str(me_person))['document_id']
    monkeypatch.setattr(hub, 'URL', 'http://wehub.test')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', False)
    fil = user(10, 'Fil', 'fil@example.com')
    wehub.users = {'fil@example.com': fil}
    # weHub knows Luca from the import (local_id); Fil's person is matched through his account
    family(wehub, local_id=f.me['family']['id'], members=[{**fil, 'role': 'admin'}],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10},
                   {'hub_id': 102, 'name': 'Luca Rossi', 'kind': 'child', 'local_id': luca, 'user_hub_id': None}])
    wehub.access = {10: [1]}
    c = client()
    sign_in(c, wehub, 'fil@example.com')
    me = ok(c.get('/api/me'))
    assert me['family']['id'] == f.me['family']['id']
    assert {p['id']: p['name'] for p in me['people']} == {me_person: 'Fil', luca: 'Luca Rossi'}
    assert ok(c.get(f'/api/documents/{doc_luca}'))['person_id'] == luca
    assert ok(c.get(f'/api/documents/{doc_me}'))['person_id'] == me_person
    # Luca removed in weHub: his documents stay, about the whole family
    family(wehub, version=2, local_id=f.me['family']['id'], members=[{**fil, 'role': 'admin'}],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}])
    hub.sync_all()
    assert ok(c.get(f'/api/documents/{doc_luca}'))['person_id'] is None
    assert ok(c.get('/api/documents'))['total'] == 2


def test_no_access(client, wehub):
    wehub.users = {'tata@example.com': user(12, 'Tata', 'tata@example.com')}
    assert 'login?error=' in sign_in(client(), wehub, 'tata@example.com')


def test_export_for_the_import(client, wehub, monkeypatch):
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    c = client()
    sign_up(c)
    ok(c.post('/api/family/people', json={'name': 'Luca', 'birth_date': '2025-01-10'}), 201)
    assert client().get('/api/hub/export').status_code == 401
    f = ok(client().get('/api/hub/export', headers={'Authorization': 'Bearer ' + KEY}))['families'][0]
    people = {p['name']: p for p in f['people']}
    assert people['Fil']['member_email'] == 'fil@example.com' and people['Luca']['member_email'] is None
    assert people['Luca']['birth_date'] == '2025-01-10'


def merge(c, into, families, key=KEY):
    return c.post('/api/hub/merge', json={'into': into, 'families': families}, headers={'Authorization': 'Bearer ' + key})


def test_merge_two_families_made_separately(client, wehub, monkeypatch):
    from conftest import Family
    monkeypatch.setattr(hub, 'URL', '')
    monkeypatch.setattr(auth, 'PASSWORD_LOGIN', True)
    fil = Family(client)
    sara = client()
    b = sign_up(sara, email='sara@example.com', name='Sara')
    luca_a = next(p['id'] for p in ok(fil.c.post('/api/family/people', json={'name': 'Luca'}), 201) if p['name'] == 'Luca')
    luca_b = next(p['id'] for p in ok(sara.post('/api/family/people', json={'name': 'LUCA', 'birth_date': '2025-01-10'}), 201) if p['name'] == 'LUCA')
    same = pdf_with_text(['Bolletta luce marzo'])
    fil.upload(same, 'a.pdf')
    dup = fil.upload(same, 'b.pdf', c=sara)['document_id']
    own = fil.upload(pdf_with_text(['Referto di Luca']), 'r.pdf', c=sara, person_id=str(luca_b))['document_id']
    r = ok(merge(client(), fil.me['family']['id'], [b['family']['id']]))
    assert r['report']['documents'] == 2 and r['report']['duplicates_to_trash'] == 1 and r['report']['people_merged'] == 1
    me = ok(sara.get('/api/me'))
    assert me['family']['id'] == fil.me['family']['id']
    people = {p['name']: p for p in me['people']}
    assert set(people) == {'Fil', 'Sara', 'Luca'} and people['Luca']['birth_date'] == '2025-01-10'
    assert people['Sara']['user_id'] == me['user']['id']
    assert ok(sara.get(f'/api/documents/{own}'))['person_id'] == luca_a
    assert ok(sara.get(f'/api/documents/{dup}'))['deleted_at']           # identical file: in the trash, recoverable
    assert ok(sara.get('/api/documents'))['total'] == 2
    assert ok(sara.get('/api/documents?q=referto'))['total'] == 1


# ---------- Links with doTrack and eaTrack (links.py) ----------

def _hub_family(client, wehub):
    fil = user(10, 'Fil', 'fil@example.com')
    wehub.users = {'fil@example.com': fil}
    family(wehub, members=[{**fil, 'role': 'admin'}],
           people=[{'hub_id': 100, 'name': 'Fil', 'user_hub_id': 10}, {'hub_id': 102, 'name': 'Luca', 'kind': 'child', 'user_hub_id': None}])
    wehub.access = {10: [1]}
    c = client()
    sign_in(c, wehub, 'fil@example.com')
    return c


def _upload(c, text='Carta di identità Luca'):
    import io
    from conftest import run_queue
    r = ok(c.post('/api/imports', data={'file': (io.BytesIO(pdf_with_text([text])), 'ci.pdf')}, content_type='multipart/form-data'), 201)
    run_queue()
    return ok(c.get(f"/api/imports/{r['id']}"))['document_id']


class DoTrack:
    """Stands in for weHub → doTrack."""

    def __init__(self):
        self.calls, self.down, self.answer = [], False, {'item_id': 5, 'created': True}

    def __call__(self, method, url, **kw):
        import requests
        if self.down:
            raise requests.ConnectionError()
        self.calls.append((method, url.split('/families/1', 1)[1], kw.get('json')))
        r = requests.Response()
        r.status_code, r._content = 201, __import__('json').dumps(self.answer).encode()
        return r


def test_a_document_keeps_its_deadline_in_dotrack(client, wehub, monkeypatch):
    import requests
    import links
    monkeypatch.setattr(auth, 'BASE_URL', 'https://pa.example')
    c = _hub_family(client, wehub)
    dt = DoTrack()
    monkeypatch.setattr(requests, 'request', dt)
    doc = _upload(c)
    luca = next(p['id'] for p in ok(c.get('/api/me'))['people'] if p['name'] == 'Luca')
    ok(c.put(f'/api/documents/{doc}', json={'doc_type': "Carta d'identità", 'person_id': luca, 'expiry_date': '2031-03-04'}))
    assert dt.calls == []                                   # not asked for: doTrack is left alone
    d = ok(c.put(f'/api/documents/{doc}', json={'dotrack': True, 'dotrack_remind': 60}))
    assert (d['dotrack'], d['dotrack_state'], d['dotrack_item']) == (1, 'sent', 5)
    method, path, payload = dt.calls[-1]
    assert (method, path) == ('PUT', f'/deadlines/patrack-{doc}')
    assert payload['title'] == "Carta d'identità" and payload['due_date'] == '2031-03-04' and payload['remind_days'] == 60
    assert payload['person_hub_id'] == 102 and payload['url'] == f'https://pa.example/#/doc/{doc}' and payload['category'] is None
    ok(c.put(f'/api/documents/{doc}', json={'notes': 'nel cassetto'}))
    assert len(dt.calls) == 1                               # nothing doTrack shows changed
    # doTrack down: waits, then goes on the next round
    dt.down = True
    assert ok(c.put(f'/api/documents/{doc}', json={'expiry_date': '2041-03-04'}))['dotrack_state'] == 'pending'
    dt.down = False
    links.push_pending()
    assert dt.calls[-1][2]['due_date'] == '2041-03-04' and ok(c.get(f'/api/documents/{doc}'))['dotrack_state'] == 'sent'
    # To the trash: the deadline goes too; restored: back
    ok(c.delete(f'/api/documents/{doc}'))
    links.push_pending()
    assert dt.calls[-1][:2] == ('DELETE', f'/deadlines/patrack-{doc}')
    assert ok(c.get(f'/api/documents/{doc}'))['dotrack_item'] is None
    ok(c.post(f'/api/documents/{doc}/restore'))
    assert dt.calls[-1][0] == 'PUT'
    # Turned off: removed; deleted by someone in doTrack: turned off here
    ok(c.put(f'/api/documents/{doc}', json={'dotrack': False}))
    assert dt.calls[-1][0] == 'DELETE'
    dt.answer = {'item_id': 5, 'deleted': True}
    d = ok(c.put(f'/api/documents/{doc}', json={'dotrack': True}))
    assert (d['dotrack'], d['dotrack_state']) == (0, None)
    assert c.put(f'/api/documents/{doc}', json={'dotrack_remind': 'x'}).status_code == 400


def test_documents_from_dotrack_and_plans_for_eatrack(client, wehub, monkeypatch):
    import base64
    from conftest import run_queue
    monkeypatch.setattr(auth, 'BASE_URL', 'https://pa.example')
    c = _hub_family(client, wehub)
    H = {'Authorization': 'Bearer ' + KEY}
    pdf = pdf_with_text(['Passaporto Luca'])
    body = {'file_name': 'passaporto.pdf', 'content': base64.b64encode(pdf).decode(), 'title': 'Passaporto Luca',
            'expiry_date': '2030-05-01', 'remind_days': 90, 'category': 'identity', 'dotrack_item': 8, 'person_hub_id': 102}
    post = lambda level='full', **extra: client().post(f'/api/hub/families/1/documents?user=10&level={level}', headers=H,  # noqa: E731
                                                        json={**body, **extra})
    assert post(level='').status_code == 403 and post(level='limited').status_code == 403
    assert post(content='%%%').status_code == 400
    r = ok(post(), 201)
    assert r['url'] == f"https://pa.example/#/doc/{r['id']}" and not r['duplicate']
    run_queue()
    d = ok(c.get(f"/api/documents/{r['id']}"))
    assert (d['title'], d['expiry_date'], d['category'], d['dotrack'], d['dotrack_remind'], d['dotrack_state'], d['dotrack_item']) == \
        ('Passaporto Luca', '2030-05-01', 'identity', 1, 90, 'sent', 8)
    assert next(p['name'] for p in ok(c.get('/api/me'))['people'] if p['id'] == d['person_id']) == 'Luca'
    assert d['origin']['source'] == 'dotrack'
    # The same file from another deadline: refused; from the same one: the same document
    assert post(dotrack_item=9).status_code == 409
    assert ok(post(), 201) == {**r, 'duplicate': True}
    # eaTrack: the paediatrician's plans of a child
    plans = lambda child=102, level='full': client().get(f'/api/hub/families/1/plans?user=10&child={child}&level={level}', headers=H)  # noqa: E731
    assert ok(plans()) == []
    plan = _upload(c, 'Piano svezzamento settimana 3: zucchine, carote')
    luca = d['person_id']
    ok(c.put(f'/api/documents/{plan}', json={'person_id': luca, 'eatrack_plan': True, 'doc_date': '2026-11-10', 'doc_type': 'Piano'}))
    got = ok(plans())
    assert [p['id'] for p in got] == [plan] and 'zucchine' in got[0]['excerpt'] and got[0]['url'].endswith(f'/doc/{plan}')
    assert ok(plans(child=100)) == [] and plans(level='limited').status_code == 403

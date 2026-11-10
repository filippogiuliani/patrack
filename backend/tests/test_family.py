"""People (who documents are about), members and invitations."""
from conftest import ok


def test_people(family):
    me = family.me['people']
    assert [p['name'] for p in me] == ['Fil'] and me[0]['user_id'] == family.uid
    people = ok(family.c.post('/api/family/people', json={'name': 'Luca', 'birth_date': '2025-01-10'}), 201)
    luca = next(p for p in people if p['name'] == 'Luca')
    assert luca['birth_date'] == '2025-01-10' and luca['user_id'] is None
    assert family.c.post('/api/family/people', json={'name': 'luca'}).status_code == 409
    people = ok(family.c.put(f"/api/family/people/{luca['id']}", json={'name': 'Luca M.', 'birth_date': ''}))
    assert any(p['name'] == 'Luca M.' and p['birth_date'] is None for p in people)
    # A member's person cannot be renamed or deleted from here
    ok(family.c.put(f"/api/family/people/{me[0]['id']}", json={'name': 'Altro'}))
    assert ok(family.c.get('/api/me'))['people'][0]['name'] == 'Fil'
    assert family.c.delete(f"/api/family/people/{me[0]['id']}").status_code == 400


def test_deleting_a_person_keeps_the_documents(family):
    from samples import pdf_with_text
    people = ok(family.c.post('/api/family/people', json={'name': 'Nonna'}), 201)
    nonna = next(p['id'] for p in people if p['name'] == 'Nonna')
    doc = family.upload(pdf_with_text(['x']), person_id=str(nonna))['document_id']
    ok(family.c.delete(f'/api/family/people/{nonna}'))
    assert ok(family.c.get(f'/api/documents/{doc}'))['person_id'] is None


def test_partner_joins_as_a_person(family):
    family.add_partner()
    f = ok(family.c.get('/api/family'))
    assert [m['name'] for m in f['members']] == ['Fil', 'Sara']
    assert [p['name'] for p in f['people']] == ['Fil', 'Sara']
    # Removed member: their person stays (documents about them stay), without the account link
    ok(family.c.delete(f'/api/family/members/{family.puid}'))
    sara = next(p for p in ok(family.c.get('/api/family'))['people'] if p['name'] == 'Sara')
    assert sara['user_id'] is None


def test_backup_status(family):
    import backup
    backup.create_backup('auto')
    assert ok(family.c.get('/api/family'))['backup']['last_local']

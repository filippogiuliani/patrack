"""The archive: editing, filters, free-text search, trash."""
import datetime

from conftest import ok
from samples import pdf_with_text


def add(family, lines, name='doc.pdf', **fields):
    imp = family.upload(pdf_with_text(lines), name)
    doc_id = imp['document_id']
    if fields:
        ok(family.c.put(f'/api/documents/{doc_id}', json=fields))
    return doc_id


def people(family):
    return {p['name']: p['id'] for p in ok(family.c.get('/api/me'))['people']}


def test_edit_fields(family):
    doc = add(family, ['Polizza RC auto'], 'scan.pdf')
    me = family.me['people'][0]['id']
    d = ok(family.c.put(f'/api/documents/{doc}', json={
        'title': 'Assicurazione Panda', 'category': 'insurance', 'doc_type': 'Polizza', 'person_id': me,
        'doc_date': '2026-03-01', 'expiry_date': '2027-03-01', 'amount': '1.234,50', 'issuer': 'Allianz', 'notes': 'rinnovo'}))
    assert d['title'] == 'Assicurazione Panda' and d['amount_cents'] == 123450 and d['expiry_date'] == '2027-03-01'
    assert ok(family.c.put(f'/api/documents/{doc}', json={'amount': 12.5}))['amount_cents'] == 1250
    assert ok(family.c.put(f'/api/documents/{doc}', json={'amount': ''}))['amount_cents'] is None
    assert family.c.put(f'/api/documents/{doc}', json={'category': 'nope'}).status_code == 400
    assert family.c.put(f'/api/documents/{doc}', json={'doc_date': '31/02/2026'}).status_code == 400
    assert family.c.put(f'/api/documents/{doc}', json={'amount': 'tanti'}).status_code == 400
    assert family.c.put(f'/api/documents/{doc}', json={'person_id': 9999}).status_code == 400
    # Edited fields are searchable
    assert ok(family.c.get('/api/documents?q=allianz'))['total'] == 1


def test_saving_fixes_a_document_to_review(family):
    imp = family.upload(b'\x00binary', 'x.bin')
    doc = imp['document_id']
    assert ok(family.c.get('/api/documents/facets'))['review'] == 1
    ok(family.c.put(f'/api/documents/{doc}', json={'title': 'Manuale lavatrice', 'category': 'purchases'}))
    d = ok(family.c.get(f'/api/documents/{doc}'))
    assert d['status'] == 'ready' and d['review_reason'] is None
    assert ok(family.c.get('/api/documents/facets'))['review'] == 0


def test_without_category_counts_as_to_fix(family):
    add(family, ['Qualcosa da classificare'])
    assert ok(family.c.get('/api/documents?status=review'))['total'] == 1
    assert ok(family.c.get('/api/documents?category=none'))['total'] == 1


def test_free_text_search(family):
    ok(family.c.post('/api/family/people', json={'name': 'Luca', 'birth_date': '2025-01-10'}), 201)
    luca = people(family)['Luca']
    add(family, ['Bolletta energia elettrica', 'Enel Energia'], category='home', doc_type='Bolletta luce', doc_date='2026-03-15')
    add(family, ['Bolletta gas naturale', 'consumo Smc'], category='home', doc_date='2026-03-20')
    add(family, ['Fattura energia elettrica'], category='home', doc_date='2026-05-02')
    add(family, ['Referto esame emocromo', 'Laboratorio analisi'], category='health', person_id=luca, doc_date='2026-02-01')
    add(family, ['Referto visita oculistica'], category='health', doc_date='2026-02-03')

    def titles(q):
        return sorted(d['doc_type'] or d['title'] for d in ok(family.c.get('/api/documents', query_string={'q': q}))['items'])

    def count(q):
        return ok(family.c.get('/api/documents', query_string={'q': q}))['total']

    assert count('bolletta luce marzo') == 1           # "luce" → energia elettrica; marzo → the date
    assert count('bolletta marzo') == 2
    assert count('bollette') == 3                       # plural finds the singular, and "fattura"
    assert count('luce') == 2                           # energia elettrica, any month
    assert count('referto sangue Luca') == 1            # sangue → emocromo; Luca → the person
    assert count('referto luca') == 1
    assert count('referti') == 2
    assert count('sanità') == 2                         # category word
    assert count('2026') == 5
    assert count('ENEL') == 1                           # case and accents don't matter
    assert count('qualcosachenonce') == 0
    # A snippet shows where the words were found
    d = ok(family.c.get('/api/documents', query_string={'q': 'emocromo'}))['items'][0]
    assert '[[' in d['snippet'] and 'mocromo' in d['snippet'].lower()


def test_filters(family):
    ok(family.c.post('/api/family/people', json={'name': 'Luca'}), 201)
    luca = people(family)['Luca']
    today = datetime.date.today()
    add(family, ['Carta identita'], category='identity', person_id=luca, expiry_date=(today + datetime.timedelta(days=20)).isoformat(),
        doc_date='2024-05-01')
    add(family, ['Patente'], category='identity', expiry_date=(today - datetime.timedelta(days=5)).isoformat(), doc_date='2025-01-01')
    add(family, ['Garanzia frigo'], category='purchases', expiry_date=(today + datetime.timedelta(days=400)).isoformat())

    def total(**qs):
        return ok(family.c.get('/api/documents', query_string=qs))['total']

    assert total(person=str(luca)) == 1 and total(person='family') == 2
    assert total(category='identity') == 2 and total(category='purchases') == 1
    assert total(year='2024') == 1 and total(year='2025') == 1
    assert total(expiry='soon') == 1 and total(expiry='expired') == 1 and total(expiry='any') == 3
    assert total(category='identity', expiry='soon') == 1
    f = ok(family.c.get('/api/documents/facets'))
    assert f['categories'] == {'identity': 2, 'purchases': 1} and f['soon'] == 1 and f['expired'] == 1
    assert str(today.year) in f['years'] and '2024' in f['years']
    assert f['people'] == {str(luca): 1, 'family': 2}
    # Sorting by expiry: the closest first
    items = ok(family.c.get('/api/documents', query_string={'sort': 'expiry'}))['items']
    dates = [i['expiry_date'] for i in items]
    assert dates == sorted(dates)


def test_trash(family):
    doc = add(family, ['Vecchio contratto'])
    ok(family.c.delete(f'/api/documents/{doc}'))
    assert ok(family.c.get('/api/documents'))['total'] == 0
    assert ok(family.c.get('/api/documents?trash=1'))['total'] == 1
    assert ok(family.c.get('/api/documents?q=contratto'))['total'] == 0
    ok(family.c.post(f'/api/documents/{doc}/restore'))
    assert ok(family.c.get('/api/documents?q=contratto'))['total'] == 1
    # Deleting for good only from the trash
    assert family.c.delete(f'/api/documents/{doc}?permanent=1').status_code == 400
    ok(family.c.delete(f'/api/documents/{doc}'))
    ok(family.c.delete(f'/api/documents/{doc}?permanent=1'))
    assert family.c.get(f'/api/documents/{doc}').status_code == 404


def test_trash_is_purged_after_30_days(family):
    import db
    import imports
    import storage
    doc = add(family, ['x'])
    ok(family.c.delete(f'/api/documents/{doc}'))
    with db.transaction() as conn:
        stored = conn.execute('SELECT stored_name FROM documents WHERE id = ?', (doc,)).fetchone()[0]
        conn.execute("UPDATE documents SET deleted_at = datetime('now', '-31 days') WHERE id = ?", (doc,))
    imports.purge_trash()
    assert family.c.get(f'/api/documents/{doc}').status_code == 404 and not storage.exists(stored)


def test_duplicate_of_a_trashed_document(family):
    data = pdf_with_text(['Uguale'])
    first = family.upload(data)
    ok(family.c.delete(f"/api/documents/{first['document_id']}"))
    dup = family.upload(data)
    assert dup['status'] == 'duplicate' and dup['duplicate_deleted']


def test_reprocess(family):
    doc = add(family, ['Testo da rileggere'])
    d = ok(family.c.post(f'/api/documents/{doc}/reprocess'))
    assert d['status'] == 'processing'
    from conftest import run_queue
    run_queue()
    assert ok(family.c.get(f'/api/documents/{doc}'))['status'] == 'ready'


def test_partner_sees_the_family_archive(family):
    p = family.add_partner()
    add(family, ['Mutuo casa'])
    assert ok(p.get('/api/documents?q=mutuo'))['total'] == 1
    names = [x['name'] for x in ok(p.get('/api/me'))['people']]
    assert names == ['Fil', 'Sara']

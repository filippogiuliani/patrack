"""The tax return view: the year's expenses by kind and person, what is missing, the ZIP for the CAF."""
import csv
import io
import zipfile

from conftest import ok
from samples import pdf_with_text


def _doc(f, text, **fields):
    doc = f.upload(pdf_with_text([text]), f'{abs(hash(text))}.pdf')['document_id']
    if fields:
        ok(f.c.put(f'/api/documents/{doc}', json=fields))
    return doc


def test_tax_year(family):
    f = family
    luca = next(p['id'] for p in ok(f.c.post('/api/family/people', json={'name': 'Luca'}), 201) if p['name'] == 'Luca')
    farmacia = _doc(f, 'Farmacia Centrale scontrino', doc_type='Scontrino farmacia', doc_date='2025-03-10', amount='12,50', person_id=luca)
    dentista = _doc(f, 'Studio dentistico fattura', doc_type='Fattura dentista', doc_date='2025-06-02', amount='180', category='health')
    _doc(f, 'Referto esame del sangue', doc_type='Referto', doc_date='2025-04-01', category='health')        # not an expense
    asilo = _doc(f, 'Retta asilo nido settembre', doc_type='Retta asilo nido', doc_date='2025-09-01', person_id=luca)  # no amount
    nuoto = _doc(f, 'Corso di nuoto Luca', tax_kind='sport', person_id=luca)                                  # no date
    _doc(f, 'Farmacia del Corso', doc_type='Scontrino farmacia', doc_date='2025-05-05', amount='9', tax_kind='none')
    _doc(f, 'Farmacia anno prima', doc_type='Scontrino farmacia', doc_date='2024-12-30', amount='5')
    bolletta = _doc(f, 'Bolletta luce', doc_type='Bolletta luce', doc_date='2025-02-01', amount='80', category='home')

    t = ok(f.c.get('/api/tax?year=2025'))
    assert t['year'] == 2025 and 2024 in t['years'] and 2025 in t['years']
    kinds = {k['kind']: k for k in t['kinds']}
    assert set(kinds) == {'medical', 'school'}
    med = kinds['medical']
    assert (med['total_cents'], med['count']) == (19250, 2) and [d['id'] for d in med['documents']] == [farmacia, dentista]
    assert {(p['name'], p['total_cents']) for p in med['people']} == {('Luca', 1250), (None, 18000)}
    assert [d['id'] for d in t['missing_amount']] == [asilo] and [d['id'] for d in t['missing_date']] == [nuoto]
    assert t['total_cents'] == 19250 and 'stored_name' not in med['documents'][0]
    # The proposal is shown on the document; choosing by hand wins
    d = ok(f.c.get(f'/api/documents/{bolletta}'))
    assert d['tax_guess'] is None and d['tax_kind'] is None
    ok(f.c.put(f'/api/documents/{bolletta}', json={'tax_kind': 'other'}))
    assert 'other' in {k['kind'] for k in ok(f.c.get('/api/tax?year=2025'))['kinds']}
    assert f.c.put(f'/api/documents/{bolletta}', json={'tax_kind': 'yacht'}).status_code == 400
    ok(f.c.put(f'/api/documents/{bolletta}', json={'tax_kind': None}))
    # Last year by default; a year with nothing: empty, and no ZIP
    assert ok(f.c.get('/api/tax?year=2019'))['kinds'] == []
    assert f.c.get('/api/tax/export?year=2019').status_code == 404


def test_tax_export_zip(family):
    f = family
    a = _doc(f, 'Farmacia uno', doc_type='Scontrino farmacia', doc_date='2025-03-10', amount='12,50')
    _doc(f, 'Farmacia due', doc_type='Scontrino farmacia', doc_date='2025-03-10', amount='3')
    _doc(f, 'Retta asilo nido', doc_type='Retta asilo nido', doc_date='2025-09-01', amount='300')
    r = f.c.get('/api/tax/export?year=2025')
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    assert 'paTrack-2025.zip' in r.headers['Content-Disposition']
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = sorted(z.namelist())
    assert names == ['Scuola e asilo nido/2025-09-01 Retta asilo nido.pdf', 'Spese sanitarie/2025-03-10 Scontrino farmacia (2).pdf',
                     'Spese sanitarie/2025-03-10 Scontrino farmacia.pdf', 'riepilogo-2025.csv']
    # The original, byte for byte (decrypted)
    assert z.read('Spese sanitarie/2025-03-10 Scontrino farmacia.pdf') == f.c.get(f'/api/documents/{a}/file').data
    rows = list(csv.reader(io.StringIO(z.read('riepilogo-2025.csv').decode('utf-8-sig')), delimiter=';'))
    assert rows[0] == ['Tipo', 'Persona', 'Data', 'Documento', 'Emesso da', 'Importo (€)', 'File']
    assert rows[1][:6] == ['Spese sanitarie', 'Tutta la famiglia', '2025-03-10', 'Scontrino farmacia', '', '12,50']
    assert rows[3][0] == 'Scuola e asilo nido' and rows[3][5] == '300,00'

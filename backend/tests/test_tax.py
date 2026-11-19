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


def test_receipts_on_a4_per_person(family):
    """Each person's receipts of the year on A4 sheets, three columns side by side, filled as much as possible."""
    from PIL import Image
    import receipts
    from samples import text_image
    f = family
    luca = next(p['id'] for p in ok(f.c.post('/api/family/people', json={'name': 'Luca'}), 201) if p['name'] == 'Luca')
    for i in range(7):
        tall = text_image([f'FARMACIA CENTRALE {i}', 'TACHIPIRINA 12,50', 'TOTALE 12,50'] * 8, fmt='PNG', size=(600, 2200))
        doc = f.upload(tall, f'scontrino{i}.png')['document_id']
        ok(f.c.put(f'/api/documents/{doc}', json={'doc_type': 'Scontrino farmacia', 'doc_date': f'2025-03-1{i}',
                                                 'amount': '12,50', 'person_id': luca}))
    _doc(f, 'Fattura dentista', doc_type='Fattura dentista', doc_date='2025-06-02', amount='180', person_id=luca)  # an A4 invoice

    t = ok(f.c.get('/api/tax?year=2025'))
    assert [(r['name'], r['count']) for r in t['receipts'] if r['count']] == [('Luca', 7)]
    assert f.c.put(f'/api/tax/people/{luca}', json={'tax_code': 'nope'}).status_code == 400
    ok(f.c.put(f'/api/tax/people/{luca}', json={'tax_code': 'rssmra80a01h501u'}))
    assert next(r for r in ok(f.c.get('/api/tax?year=2025'))['receipts'] if r['person_id'] == luca)['tax_code'] == 'RSSMRA80A01H501U'

    r = f.c.get(f'/api/tax/receipts?year=2025&person={luca}')
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and 'paTrack-2025-Luca.pdf' in r.headers['Content-Disposition']
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(r.data)
    w, h = pdf[0].get_size()
    assert abs(w - 595) < 3 and abs(h - 842) < 3          # A4 portrait
    assert 1 <= len(pdf) <= 3                               # 7 long receipts, one or two per column, three columns a sheet
    assert f.c.get('/api/tax/receipts?year=2019&person=%d' % luca).status_code == 404


def test_receipts_packing_fills_columns():
    import receipts
    heights = [700, 650, 400, 350, 300, 250, 200, 100]

    def check(cols, cap, overhead):
        assert all(sum(b - t + overhead for _, t, b in c) <= cap for c in cols)       # nothing over a column
        for i, h in enumerate(heights):                                             # every receipt whole, once
            parts = sorted((t, b) for c in cols for j, t, b in c if j == i)
            assert parts[0][0] == 0 and parts[-1][1] == h and all(a[1] == b[0] for a, b in zip(parts, parts[1:]))
    # best fit: the small ones fill the gaps left by the tall ones
    cols = receipts.pack(heights, 1000, overhead=0, min_piece=50, split_min=10_000)
    check(cols, 1000, 0)
    assert len(cols) == 3 and all(len({b - t for _, t, b in c}) for c in cols)
    # with splitting allowed the space left at the bottom is used: 2950 in columns of 1000 still three, all whole
    cols = receipts.pack(heights * 2, 1000, overhead=0, min_piece=50, split_min=150)
    assert len(cols) == 6                                   # 5900: six columns, no seventh for the leftovers


def test_receipts_sheet_layout():
    """Receipts of known size: kept upright, three columns a sheet, as many as fit; a very long one goes on."""
    from PIL import Image, ImageDraw
    import pypdfium2 as pdfium
    import receipts

    def receipt(h_mm):                       # 80 mm paper, a black frame so trimming keeps all of it
        img = Image.new('L', (round(80 * receipts.MM), round(h_mm * receipts.MM)), 255)
        ImageDraw.Draw(img).rectangle((0, 0, img.width - 1, img.height - 1), outline=0, width=6)
        return img
    # at column width (~62 mm) a 100 mm receipt is ~78 mm tall: three fit in a 270 mm column
    pdf = pdfium.PdfDocument(receipts.build_pdf([(receipt(100), f'r{i}') for i in range(9)], 'Luca · Scontrini 2025'))
    assert len(pdf) == 1                                    # 9 receipts: 3 columns × 3
    pdf = pdfium.PdfDocument(receipts.build_pdf([(receipt(100), f'r{i}') for i in range(10)], 'x'))
    assert len(pdf) == 2
    # one receipt longer than a column is cut and goes on in the next column, no part shorter than MIN_PIECE
    cols = receipts.pack([round(500 * 62 / 80 * receipts.MM)])
    assert len(cols) == 2 and all(b - t >= receipts.MIN_PIECE for c in cols for _, t, b in c)
    # long receipts fill the space left at the bottom of the columns: fewer sheets than one per column
    pdf = pdfium.PdfDocument(receipts.build_pdf([(receipt(240), f'r{i}') for i in range(8)], 'x'))
    assert len(pdf) == 2                                    # 8 × ~186 mm in ~270 mm columns: 6 columns, not 8 (3 sheets)

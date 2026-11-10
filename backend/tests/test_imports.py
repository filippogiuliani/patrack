"""The import queue: storing originals, reading text and OCR, duplicates, failures that never go silent, retry."""
import hashlib
import io
import os
import shutil

import pytest

import imports
import processing
import storage
from conftest import ok, run_queue
from samples import pdf_with_text, scanned_pdf, text_image

needs_tesseract = pytest.mark.skipif(not shutil.which('tesseract'), reason='tesseract not installed')


def test_pdf_with_text_is_archived_and_searchable(family):
    data = pdf_with_text(['Bolletta energia elettrica', 'Periodo marzo 2026', 'Totale 84,30 EUR'])
    imp = family.upload(data, 'bolletta_marzo.pdf')
    assert imp['status'] == 'done' and imp['document_id']
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['title'] == 'bolletta marzo' and doc['status'] == 'ready' and doc['text_source'] == 'pdf'
    assert 'energia elettrica' in doc['ocr_text'] and doc['pages'] == 1 and doc['has_preview']
    assert doc['origin']['source'] == 'upload' and doc['origin']['user_name'] == 'Fil'
    # The original comes back byte for byte
    r = family.c.get(f"/api/documents/{doc['id']}/file")
    assert r.status_code == 200 and r.data == data and r.mimetype == 'application/pdf'
    assert family.c.get(f"/api/documents/{doc['id']}/preview").mimetype == 'image/jpeg'
    # …and is encrypted on disk
    raw = open(os.path.join(storage.files_dir(), doc_stored_name(doc['id'])[:2], doc_stored_name(doc['id'])), 'rb').read()
    assert raw.startswith(b'PTK1') and b'energia' not in raw and data not in raw


def doc_stored_name(doc_id):
    import db
    with db.transaction() as conn:
        return conn.execute('SELECT stored_name FROM documents WHERE id = ?', (doc_id,)).fetchone()[0]


@needs_tesseract
def test_photo_is_read_with_ocr(family):
    imp = family.upload(text_image(['REFERTO ESAME SANGUE', 'Emocromo completo']), 'IMG_1234.png', source='scan')
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['text_source'] == 'ocr' and 'EMOCROMO' in doc['ocr_text'].upper()
    assert doc['origin']['source'] == 'scan'


@needs_tesseract
def test_scanned_pdf_is_read_with_ocr(family):
    imp = family.upload(scanned_pdf(['CONTRATTO DI LOCAZIONE', 'Canone mensile']), 'contratto.pdf')
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['text_source'] == 'ocr' and 'LOCAZIONE' in doc['ocr_text'].upper()


def test_duplicate_is_reported_not_stored(family):
    data = pdf_with_text(['Polizza auto'])
    first = family.upload(data, 'polizza.pdf')
    files_before = sum(len(f) for _, _, f in os.walk(storage.files_dir()))
    dup = family.upload(data, 'polizza (1).pdf')
    assert dup['status'] == 'duplicate' and dup['duplicate_of'] == first['document_id'] and dup['duplicate_title'] == 'polizza'
    assert sum(len(f) for _, _, f in os.walk(storage.files_dir())) == files_before
    assert ok(family.c.get('/api/documents'))['total'] == 1
    # Keep it anyway: a second document with the same content
    kept = ok(family.c.post(f"/api/imports/{dup['id']}/keep"), 201)
    run_queue()
    assert kept['document_id'] != first['document_id']
    assert ok(family.c.get('/api/documents'))['total'] == 2


def test_duplicates_are_per_family(family, client):
    from conftest import sign_up
    other = client()
    sign_up(other, email='other@example.com', name='Other')
    data = pdf_with_text(['Same file'])
    family.upload(data)
    imp = ok(other.post('/api/imports', data={'file': (io.BytesIO(data), 'x.pdf')}, content_type='multipart/form-data'), 201)
    assert imp['status'] == 'queued'


def test_failures_are_visible_and_can_be_retried(family, monkeypatch):
    def broken(data, mime):
        raise processing.ProcessingError('ocr_failed', 'tesseract crashed')
    with monkeypatch.context() as m:
        m.setattr(processing, 'process', broken)
        imp = family.upload(pdf_with_text(['Something to read here']), 'x.pdf')
    # The import shows the error, the document is still in the archive, "da sistemare"
    assert imp['status'] == 'error' and imp['error'] == 'ocr_failed' and 'crashed' in imp['error_detail']
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['status'] == 'review' and doc['review_reason'] == 'ocr_failed'
    assert ok(family.c.get('/api/documents?status=review'))['total'] == 1
    assert ok(family.c.get('/api/sync'))['errors'] == 1
    # Fixed: "Riprova"
    retried = ok(family.c.post(f"/api/imports/{imp['id']}/retry"))
    assert retried['status'] == 'queued'
    run_queue()
    imp = ok(family.c.get(f"/api/imports/{imp['id']}"))
    assert imp['status'] == 'done' and imp['attempts'] == 2
    assert ok(family.c.get(f"/api/documents/{imp['document_id']}"))['status'] == 'ready'


def test_unexpected_crash_is_caught(family, monkeypatch):
    monkeypatch.setattr(processing, 'process', lambda data, mime: 1 / 0)
    imp = family.upload(pdf_with_text(['x']), 'x.pdf')
    assert imp['status'] == 'error' and imp['error'] == 'processing_failed' and 'ZeroDivisionError' in imp['error_detail']


def test_retry_all(family, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(processing, 'process', lambda data, mime: 1 / 0)
        family.upload(pdf_with_text(['a']), 'a.pdf')
        family.upload(pdf_with_text(['b']), 'b.pdf')
    assert ok(family.c.post('/api/imports/retry-all'))['retried'] == 2
    run_queue()
    assert ok(family.c.get('/api/imports'))['counts'] == {'done': 2}


def test_empty_and_unknown_files(family):
    empty = family.upload(b'', 'empty.pdf')
    assert empty['status'] == 'error' and empty['error'] == 'empty_file' and not empty['document_id']
    # The browser re-sends files that never arrived; the server cannot retry them
    assert family.c.post(f"/api/imports/{empty['id']}/retry").status_code == 400
    odd = family.upload(b'\x00\x01binary stuff', 'archive.xyz')
    doc = ok(family.c.get(f"/api/documents/{odd['document_id']}"))
    assert odd['status'] == 'done' and doc['status'] == 'review' and doc['review_reason'] == 'unsupported_format'
    # Unknown types are downloaded, never shown inline
    r = family.c.get(f"/api/documents/{doc['id']}/file")
    assert r.headers['Content-Disposition'].startswith('attachment') and r.mimetype == 'application/octet-stream'


def test_too_large(family, monkeypatch):
    monkeypatch.setattr(imports, 'MAX_FILE', 1000)
    imp = family.upload(b'%PDF' + b'0' * 2000, 'big.pdf')
    assert imp['status'] == 'error' and imp['error'] == 'too_large'


def test_protected_pdf_needs_fixing(family, monkeypatch):
    imp = family.upload(b'%PDF-1.4\nnot really a pdf', 'broken.pdf')
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert imp['status'] == 'done' and doc['status'] == 'review' and doc['review_reason'] in ('pdf_damaged', 'pdf_protected')


def test_hints_from_the_upload(family):
    person = family.me['people'][0]['id']
    imp = family.upload(pdf_with_text(['x y z w k']), 'a.pdf', person_id=str(person), category='health', title='Referto')
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['person_id'] == person and doc['category'] == 'health' and doc['title'] == 'Referto'


def test_queue_is_per_family_and_can_be_cleared(family, client):
    from conftest import sign_up
    imp = family.upload(pdf_with_text(['a']), 'a.pdf')
    other = client()
    sign_up(other, email='o@example.com', name='O')
    assert ok(other.get('/api/imports'))['items'] == []
    assert other.get(f"/api/imports/{imp['id']}").status_code == 404
    assert other.get(f"/api/documents/{imp['document_id']}").status_code == 404
    assert other.get(f"/api/documents/{imp['document_id']}/file").status_code == 404
    ok(family.c.post('/api/imports/dismiss-done'))
    assert ok(family.c.get('/api/imports'))['items'] == []


def test_shortcut_upload_with_token(family, client):
    t = ok(family.c.post('/api/account/tokens', json={'name': 'iPhone'}), 201)['token']
    phone = client()
    data = text_image(['Ricevuta'], fmt='JPEG')
    r = phone.post('/api/imports', data={'file': (io.BytesIO(data), 'photo.jpg')}, content_type='multipart/form-data',
                   headers={'Authorization': 'Bearer ' + t})
    imp = ok(r, 201)
    assert imp['source'] == 'shortcut' and imp['user_name'] == 'Fil'
    assert phone.post('/api/imports', data={'file': (io.BytesIO(data), 'p.jpg')}, content_type='multipart/form-data').status_code == 401


def test_heic_photo(family):
    pillow_heif = pytest.importorskip('pillow_heif')
    from PIL import Image
    pillow_heif.register_heif_opener()
    img = Image.open(io.BytesIO(text_image(['Scontrino'])))
    out = io.BytesIO()
    try:
        img.save(out, 'HEIF')
    except Exception:
        pytest.skip('HEIF encoder not available')
    imp = family.upload(out.getvalue(), 'IMG_0001.HEIC')
    doc = ok(family.c.get(f"/api/documents/{imp['document_id']}"))
    assert doc['mime'] == 'image/heic' and doc['has_preview']


def test_file_is_never_lost_when_key_is_missing(app, tmp_path):
    """With files on disk and no key, the server refuses to start instead of making a new key."""
    storage.put(b'hello')
    os.remove(storage.key_path())
    storage.reset_key_cache()
    with pytest.raises(RuntimeError):
        storage.check_key()


def test_sha_matches_original(family):
    data = pdf_with_text(['abc'])
    imp = family.upload(data)
    import db
    with db.transaction() as conn:
        sha = conn.execute('SELECT sha256 FROM documents WHERE id = ?', (imp['document_id'],)).fetchone()[0]
    assert sha == hashlib.sha256(data).hexdigest()


def test_manage_verify_and_reindex(family, capsys):
    import db
    import manage
    imp = family.upload(pdf_with_text(['Contratto mutuo casa']))
    assert manage.main(['manage.py', 'verify']) == 0
    with db.transaction() as conn:
        conn.execute('DELETE FROM documents_fts')
    assert ok(family.c.get('/api/documents?q=mutuo'))['total'] == 0
    assert manage.main(['manage.py', 'reindex']) == 0
    assert ok(family.c.get('/api/documents?q=mutuo'))['total'] == 1
    # A file changed on disk is reported
    with db.transaction() as conn:
        conn.execute("UPDATE documents SET sha256 = 'x' WHERE id = ?", (imp['document_id'],))
    assert manage.main(['manage.py', 'verify']) == 1
    assert 'content changed' in capsys.readouterr().out

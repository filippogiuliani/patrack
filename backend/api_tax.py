"""API: the year's documents for the tax return (730 / Redditi), grouped by kind of expense and by person.

It collects, it does not compute: totals of the amounts written on the documents, the documents still missing an
amount or a date, and a ZIP with the originals (a folder per kind) and a CSV summary to give to the CAF or the
accountant. No deduction rules, thresholds or percentages: those change every year and are the CAF's job.

Each document has a kind (documents.tax_kind): chosen by hand, or NULL = proposed from its category, type, issuer and
text (guess()); 'none' = not for the tax return. The year is the document's date (doc_date)."""
import csv
import datetime
import io
import re
import zipfile

from flask import Blueprint, Response, abort, g, jsonify, request

import db
import storage

bp = Blueprint('tax', __name__)

KINDS = ['medical', 'school', 'mortgage', 'insurance', 'sport', 'vet', 'home_works', 'rent', 'donations', 'other']
KIND_NAMES = {'medical': 'Medical expenses', 'school': 'School and nursery', 'mortgage': 'Mortgage interest',
              'insurance': 'Life and accident insurance', 'sport': "Children's sport", 'vet': 'Vet', 'home_works': 'Home works and bonuses',
              'rent': 'Rent', 'donations': 'Donations', 'other': 'Other'}   # folder names in the ZIP (translated)
NONE = 'none'

# Proposal: words in the type/title/issuer (and, for a few, the text) → kind. First match wins.
_WORDS = [
    ('medical', r'farmaci[ae]|parafarmacia|scontrino parlante|ticket|visita|specialist|odontoiatr|dentist|ortodon|analisi|'
                r'laboratorio|ottic|occhial|lenti|fisioterap|psicolog|logoped|osteopat|ecograf|radiolog|ospedal|asl\b|'
                r'poliambulatori|dispositiv[oi] medic|apparecchi[oi] acustic|farmaco'),
    ('school', r'asilo|nido|scuola|iscrizione|mensa|retta|universit|tasse universitarie|gita scolastica|libri scolastici'),
    ('mortgage', r'mutuo|interessi passivi'),
    ('insurance', r'polizza vita|assicurazione vita|polizza infortuni|assicurazione infortuni|premio assicurativo vita'),
    ('sport', r'palestra|piscina|sport|calcio|danza|nuoto|associazione sportiva|a\.?s\.?d\.?'),
    ('vet', r'veterinar|clinica veterinaria'),
    ('home_works', r'ristrutturazion|bonus casa|ecobonus|superbonus|bonus mobili|lavori edili'),
    ('rent', r'canone di locazione|affitto studenti|contratto di locazione'),
    ('donations', r'erogazione liberale|donazione|onlus|\bets\b'),
]
_EXPENSE = re.compile(r'fattura|ricevuta|scontrino|parcella|quietanza|pagamento|bonifico|retta|ticket', re.I)
_COMPILED = [(k, re.compile(p, re.I)) for k, p in _WORDS]


def guess(doc):
    """The proposed kind of a document (None = probably not an expense for the tax return)."""
    head = ' '.join(str(doc[k] or '') for k in ('doc_type', 'title', 'issuer'))
    for kind, rx in _COMPILED:
        if rx.search(head):
            return kind
    # The category alone says something only for an expense (a receipt, an invoice, or an amount written on it)
    looks_paid = doc['amount_cents'] or _EXPENSE.search(head) or _EXPENSE.search((doc['ocr_text'] or '')[:2000])
    if doc['category'] == 'health' and looks_paid:
        return 'medical'
    if doc['category'] == 'child' and looks_paid and _COMPILED[1][1].search((doc['ocr_text'] or '')[:2000]):
        return 'school'
    return None


def kind_of(doc):
    """(kind or None, chosen by hand?)"""
    if doc['tax_kind'] == NONE:
        return None, True
    if doc['tax_kind'] in KINDS:
        return doc['tax_kind'], True
    return guess(doc), False


def _year():
    try:
        y = int(request.args.get('year') or 0)
    except ValueError:
        y = 0
    return y if 1990 <= y <= 2200 else datetime.date.today().year - 1   # the return is for last year


def _collect(conn, year):
    """The year's documents for the tax return and those that might be, but lack a date."""
    people = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (g.family_id,))}
    rows = conn.execute(f'''SELECT id, title, doc_type, issuer, category, person_id, doc_date, amount_cents, tax_kind, status,
                                   substr(ocr_text, 1, 2000) AS ocr_text, file_name, stored_name, mime
                            FROM documents WHERE family_id = ? AND deleted_at IS NULL
                            AND (doc_date IS NULL OR strftime('%Y', doc_date) = ?)''', (g.family_id, str(year))).fetchall()
    found, no_date = [], []
    for r in rows:
        kind, chosen = kind_of(r)
        if not kind:
            continue
        item = {'id': r['id'], 'title': r['title'], 'doc_type': r['doc_type'], 'issuer': r['issuer'], 'doc_date': r['doc_date'],
                'amount_cents': r['amount_cents'], 'person_id': r['person_id'], 'person': people.get(r['person_id']),
                'kind': kind, 'chosen': chosen, 'file_name': r['file_name'], 'stored_name': r['stored_name']}
        if r['doc_date']:
            found.append(item)
        elif chosen:
            no_date.append(item)   # a guess without a date could be from any year: only those chosen by hand
    return found, no_date


def _public(item):
    return {k: v for k, v in item.items() if k != 'stored_name'}


@bp.get('/tax')
def summary():
    """?year=2025 → {year, years, kinds: [{kind, total_cents, count, people: [{person_id, name, total_cents}],
    documents}], missing_amount, missing_date}"""
    year = _year()
    with db.transaction() as conn:
        found, no_date = _collect(conn, year)
        years = [int(r[0]) for r in conn.execute('''SELECT DISTINCT strftime('%Y', doc_date) FROM documents
                                                    WHERE family_id = ? AND deleted_at IS NULL AND doc_date IS NOT NULL
                                                    ORDER BY 1 DESC''', (g.family_id,)) if r[0]]
    kinds = []
    for kind in KINDS:
        docs = sorted((d for d in found if d['kind'] == kind), key=lambda d: (d['doc_date'], d['id']))
        if not docs:
            continue
        by_person = {}
        for d in docs:
            p = by_person.setdefault(d['person_id'], {'person_id': d['person_id'], 'name': d['person'], 'total_cents': 0, 'count': 0})
            p['total_cents'] += d['amount_cents'] or 0
            p['count'] += 1
        kinds.append({'kind': kind, 'total_cents': sum(d['amount_cents'] or 0 for d in docs), 'count': len(docs),
                      'people': sorted(by_person.values(), key=lambda p: (p['name'] is None, p['name'] or '')),
                      'documents': [_public(d) for d in docs]})
    return jsonify(year=year, years=sorted(set(years) | {year}, reverse=True), kinds=kinds,
                   total_cents=sum(k['total_cents'] for k in kinds),
                   missing_amount=[_public(d) for d in found if d['amount_cents'] is None],
                   missing_date=[_public(d) for d in no_date])


def _safe(name, limit=80):
    s = re.sub(r'[^\w .,()&+-]+', '_', str(name or ''), flags=re.UNICODE).strip(' ._')
    return (s or 'documento')[:limit]


def _euro(cents):
    return '' if cents is None else f'{cents / 100:.2f}'.replace('.', ',')


@bp.get('/tax/export')
def export():
    """ZIP: <kind>/<date> <title>.<ext> for every document of the year, plus riepilogo.csv (Excel-friendly, ';')."""
    import i18n
    year = _year()
    with db.transaction() as conn:
        found, _ = _collect(conn, year)
    if not found:
        abort(404, 'No documents for the tax return in this year')
    lang = i18n.language()
    buf = io.BytesIO()
    summary_csv = io.StringIO()
    w = csv.writer(summary_csv, delimiter=';')
    w.writerow([i18n.tr(h, lang) for h in ('Kind', 'Person', 'Date', 'Document', 'Issuer', 'Amount (€)', 'File')])
    used = set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for d in sorted(found, key=lambda d: (KINDS.index(d['kind']), d['doc_date'], d['id'])):
            folder = _safe(i18n.tr(KIND_NAMES[d['kind']], lang), 40)
            ext = d['file_name'].rsplit('.', 1)[-1].lower() if '.' in d['file_name'] else 'bin'
            base = f"{folder}/{d['doc_date']} {_safe(d['doc_type'] or d['title'])}"
            path, n = f'{base}.{_safe(ext, 8)}', 2
            while path in used:
                path, n = f'{base} ({n}).{_safe(ext, 8)}', n + 1
            used.add(path)
            try:
                z.writestr(path, storage.get(d['stored_name']))
            except Exception as e:   # a missing file must not stop the export: it is listed in the summary
                print(f"[tax] document {d['id']}: {e}", flush=True)
                path = i18n.tr('missing file', lang)
            w.writerow([i18n.tr(KIND_NAMES[d['kind']], lang), d['person'] or i18n.tr('Whole family', lang), d['doc_date'],
                        d['doc_type'] or d['title'], d['issuer'], _euro(d['amount_cents']), path])
        z.writestr(i18n.tr('summary', lang) + f'-{year}.csv', '﻿' + summary_csv.getvalue())
    resp = Response(buf.getvalue(), mimetype='application/zip')
    resp.headers['Content-Disposition'] = f'attachment; filename="paTrack-{year}.zip"'
    return resp

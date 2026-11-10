"""Full-text search: the FTS5 index and the translation of a free-text query into SQL.

Every word of the query must match somewhere; a word can match the text of the document (title, type, issuer, notes,
OCR text) or what it means: a person ("Luca"), a category ("sanità"), a month ("marzo") or a year ("2025").
So "referto sangue Luca" finds the reports mentioning "sangue" that are about Luca, and "bolletta luce marzo" finds
electricity bills dated (or mentioning) March."""
import re
import unicodedata

MONTHS = {
    1: ['gennaio', 'january', 'jan', 'gen'], 2: ['febbraio', 'february', 'feb'], 3: ['marzo', 'march', 'mar'],
    4: ['aprile', 'april', 'apr'], 5: ['maggio', 'may', 'mag'], 6: ['giugno', 'june', 'jun', 'giu'],
    7: ['luglio', 'july', 'jul', 'lug'], 8: ['agosto', 'august', 'aug', 'ago'], 9: ['settembre', 'september', 'sep', 'set'],
    10: ['ottobre', 'october', 'oct', 'ott'], 11: ['novembre', 'november', 'nov'], 12: ['dicembre', 'december', 'dec', 'dic'],
}
# Words that point to a category (Italian and English, without accents)
CATEGORY_WORDS = {
    'identity': ['identita', 'documento identita', 'carta identita', 'passaporto', 'patente', 'identity', 'passport', 'licence'],
    'health': ['sanita', 'salute', 'medico', 'medica', 'sanitario', 'sanitaria', 'health', 'medical'],
    'child': ['bambino', 'bambina', 'bimbo', 'bimba', 'figlio', 'figlia', 'child', 'kid'],
    'home': ['casa', 'home', 'house'],
    'car': ['auto', 'macchina', 'car', 'veicolo'],
    'tax': ['fisco', 'tasse', 'fiscale', 'tax', 'taxes'],
    'work': ['lavoro', 'work', 'job'],
    'purchases': ['acquisti', 'acquisto', 'garanzia', 'garanzie', 'purchase', 'purchases', 'warranty'],
    'bank': ['banca', 'bank', 'conto'],
    'insurance': ['assicurazione', 'assicurazioni', 'polizza', 'insurance'],
}
# A few everyday words that documents rarely contain literally
SYNONYMS = {
    'luce': ['luce', 'energia elettrica', 'elettricita', 'kwh'],
    'gas': ['gas', 'smc'],
    'acqua': ['acqua', 'idrico', 'servizio idrico'],
    'bolletta': ['bolletta', 'fattura'],
    'bollette': ['bolletta', 'fattura'],
    'sangue': ['sangue', 'emocromo', 'ematochimic'],
    'scontrino': ['scontrino', 'documento commerciale'],
}


def normalize(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


def words(q):
    return [w for w in re.findall(r'[\w]+', normalize(q)) if w]


def fts_term(word):
    """One word as an FTS5 prefix query. Longer words lose their last vowel, so the Italian singular finds the plural
    ("bolletta" → bollett* matches bollette)."""
    w = re.sub(r'[^\w]', '', word)
    if len(w) >= 5 and w[-1] in 'aeiou':
        w = w[:-1]
    return f'"{w}"*' if w else None


def fts_phrase(text):
    parts = [fts_term(w) for w in words(text)]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else 'NEAR(' + ' '.join(parts) + ', 3)'


def index(conn, doc):
    """(Re)write the index row of a document (a sqlite Row or dict with the indexed fields)."""
    conn.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc['id'],))
    conn.execute('INSERT INTO documents_fts (rowid, title, doc_type, issuer, notes, body) VALUES (?,?,?,?,?,?)',
                 (doc['id'], doc['title'] or '', doc['doc_type'] or '', doc['issuer'] or '', doc['notes'] or '',
                  doc['ocr_text'] or ''))


def unindex(conn, doc_id):
    conn.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc_id,))


def build(q, people):
    """SQL conditions (on alias d) and parameters for the free-text query `q`; also the FTS expression used for
    snippets. `people`: [{id, name}] of the family."""
    conds, params, snippet_terms = [], [], []
    for w in words(q)[:12]:
        alternatives, alt_params = [], []
        expr = ' OR '.join(filter(None, [fts_phrase(s) for s in SYNONYMS.get(w, [w])]))
        if expr:
            alternatives.append('d.id IN (SELECT rowid FROM documents_fts WHERE documents_fts MATCH ?)')
            alt_params.append(expr)
            snippet_terms.append(f'({expr})')
        if len(w) >= 2:
            matching = [p['id'] for p in people if any(n.startswith(w) for n in words(p['name']))]
            if matching:
                alternatives.append(f"d.person_id IN ({','.join('?' * len(matching))})")
                alt_params += matching
        for cat, names in CATEGORY_WORDS.items():
            if any(n == w or (len(w) >= 4 and n.startswith(w)) for n in names):
                alternatives.append('d.category = ?')
                alt_params.append(cat)
        for month, names in MONTHS.items():
            if w in names:
                alternatives.append("strftime('%m', d.doc_date) = ?")
                alt_params.append(f'{month:02d}')
        if re.fullmatch(r'(19|20)\d\d', w):
            alternatives.append("strftime('%Y', d.doc_date) = ?")
            alt_params.append(w)
        if alternatives:
            conds.append('(' + ' OR '.join(alternatives) + ')')
            params += alt_params
    return conds, params, ' OR '.join(snippet_terms) or None

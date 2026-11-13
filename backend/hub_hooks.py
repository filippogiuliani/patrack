"""paTrack's part of the weHub link (the rest is famkit.hub): who this app's people are, what happens when a
member leaves, how two families made separately are merged. Registered in app.py with hub.use(hub_hooks)."""
import db
from famkit import hub

# ======================================================================
# This app's people: everyone documents can be about (members and people without an account)
# ======================================================================

def bump(conn, family_id):
    db.bump(conn, family_id)


def apply_people(conn, family_id, snap):
    """Every weHub person is a paTrack person; members keep the link to their account. Someone removed in weHub:
    their documents become "the whole family"."""
    seen = set()
    for p in snap['people']:
        u = conn.execute('SELECT id FROM users WHERE hub_id = ?', (p['user_hub_id'],)).fetchone() if p.get('user_hub_id') else None
        uid = u['id'] if u and conn.execute('SELECT 1 FROM members WHERE family_id = ? AND user_id = ?',
                                            (family_id, u['id'])).fetchone() else None
        r = conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id = ?', (family_id, p['hub_id'])).fetchone()
        if not r and p.get('local_id'):
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND id = ? AND hub_id IS NULL', (family_id, p['local_id'])).fetchone()
        if not r and uid:
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND user_id = ? AND hub_id IS NULL', (family_id, uid)).fetchone()
        if not r:
            r = conn.execute('SELECT id FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND hub_id IS NULL',
                             (family_id, p['name'])).fetchone()
        if r:
            pid = r['id']
            if uid:
                # Another row already stands for this member (made before weHub): merge it into this one
                other = conn.execute('SELECT id FROM people WHERE family_id = ? AND user_id = ? AND id != ?',
                                     (family_id, uid, pid)).fetchone()
                if other:
                    conn.execute('UPDATE documents SET person_id = ? WHERE person_id = ?', (pid, other['id']))
                    conn.execute('DELETE FROM people WHERE id = ?', (other['id'],))
            conn.execute('UPDATE people SET hub_id = ?, name = ?, birth_date = ?, user_id = ? WHERE id = ?',
                         (p['hub_id'], p['name'], p.get('birth_date'), uid, pid))
        else:
            if uid:
                conn.execute('UPDATE people SET user_id = NULL WHERE family_id = ? AND user_id = ?', (family_id, uid))
            pid = conn.execute('INSERT INTO people (family_id, user_id, name, birth_date, hub_id) VALUES (?,?,?,?,?)',
                               (family_id, uid, p['name'], p.get('birth_date'), p['hub_id'])).lastrowid
        seen.add(pid)
    for (pid,) in conn.execute('SELECT id FROM people WHERE family_id = ? AND hub_id IS NOT NULL', (family_id,)).fetchall():
        if pid not in seen:
            conn.execute('UPDATE documents SET person_id = NULL WHERE person_id = ?', (pid,))
            conn.execute('DELETE FROM people WHERE id = ?', (pid,))


def export_people(conn, family_id):
    rows = conn.execute('SELECT p.id, p.name, p.birth_date, u.email FROM people p '
                        'LEFT JOIN users u ON u.id = p.user_id WHERE p.family_id = ?', (family_id,))
    return [{'local_id': r['id'], 'name': r['name'], 'birth_date': r['birth_date'], 'member_email': r['email'], 'kind': 'adult'}
            for r in rows]


def on_member_removed(conn, family_id, user_id):
    conn.execute('UPDATE people SET user_id = NULL WHERE family_id = ? AND user_id = ?', (family_id, user_id))
    conn.execute('DELETE FROM api_tokens WHERE family_id = ? AND user_id = ?', (family_id, user_id))


def merge_data(conn, src, dst, report):
    """paTrack: the same person (member or same name) becomes one; documents and the import queue move. A document
    whose identical file is already in the destination goes to the trash (recoverable for 30 days)."""
    for p in conn.execute('SELECT * FROM people WHERE family_id = ?', (src,)).fetchall():
        t = None
        if p['user_id']:
            t = conn.execute('SELECT * FROM people WHERE family_id = ? AND user_id = ?', (dst, p['user_id'])).fetchone()
        if not t:
            t = conn.execute('SELECT * FROM people WHERE family_id = ? AND name = ? COLLATE NOCASE AND (user_id IS NULL OR user_id IS ?)',
                             (dst, p['name'], p['user_id'])).fetchone()
        if t:
            conn.execute('UPDATE documents SET person_id = ? WHERE person_id = ?', (t['id'], p['id']))
            if p['birth_date'] and not t['birth_date']:
                conn.execute('UPDATE people SET birth_date = ? WHERE id = ?', (p['birth_date'], t['id']))
            if p['user_id'] and not t['user_id']:
                conn.execute('DELETE FROM people WHERE id = ?', (p['id'],))
                conn.execute('UPDATE people SET user_id = ? WHERE id = ?', (p['user_id'], t['id']))
            else:
                conn.execute('DELETE FROM people WHERE id = ?', (p['id'],))
            hub.count(report, 'people_merged', 1)
        else:
            conn.execute('UPDATE people SET family_id = ? WHERE id = ?', (dst, p['id']))
    dup = conn.execute('''UPDATE documents SET deleted_at = datetime('now') WHERE family_id = ? AND deleted_at IS NULL
                          AND sha256 IN (SELECT sha256 FROM documents WHERE family_id = ? AND deleted_at IS NULL)''', (src, dst)).rowcount
    hub.count(report, 'duplicates_to_trash', dup)
    hub.count(report, 'documents', conn.execute('UPDATE documents SET family_id = ? WHERE family_id = ?', (dst, src)).rowcount)
    conn.execute('UPDATE imports SET family_id = ? WHERE family_id = ?', (dst, src))
    conn.execute('UPDATE api_tokens SET family_id = ? WHERE family_id = ?', (dst, src))

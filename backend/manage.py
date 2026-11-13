"""Server administration commands (not exposed in the app).

  python manage.py backup                 make a database backup now (consistent copy)
  python manage.py backups                list backups
  python manage.py restore FILE           restore a database backup (with the server STOPPED)
  python manage.py users                  list users and families
  python manage.py verify                 check that every document's file is there, decrypts and is unchanged
  python manage.py reindex                rebuild the search index
  python manage.py export-key             print the file encryption key (base64), to keep somewhere safe
  python manage.py import-key BASE64      write the key back (only where there is none)
"""
import base64
import hashlib
import os
import shutil
import sqlite3
import sys

from famkit import backup
import db
import search
import storage


def verify():
    conn = db.connect()
    bad = 0
    rows = conn.execute('SELECT id, title, stored_name, sha256, preview_name FROM documents').fetchall()
    for r in rows:
        try:
            data = storage.get(r['stored_name'])
            if hashlib.sha256(data).hexdigest() != r['sha256']:
                raise ValueError('content changed')
        except Exception as e:
            bad += 1
            print(f"PROBLEM document {r['id']} «{r['title']}»: {type(e).__name__}: {e}")
    print(f'{len(rows)} documents checked, {bad} with problems')
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'backup':
        print('Created:', backup.create_backup('manual'))
    elif cmd == 'backups':
        for b in backup.list_backups():
            print(f"{b['created_at']}  {b['size'] // 1024:>6} KB  {b['name']}")
    elif cmd == 'restore' and len(argv) == 3:
        source = backup.backup_path(argv[2]) or argv[2]
        sqlite3.connect(f'file:{source}?mode=ro', uri=True).execute('SELECT name FROM sqlite_master LIMIT 1')
        print('Safety copy:', backup.create_backup('pre-restore'))
        shutil.copyfile(source, db.DB_PATH)
        for ext in ('-wal', '-shm'):
            try:
                os.remove(db.DB_PATH + ext)
            except FileNotFoundError:
                pass
        db.init_db()
        print('Restored from', source)
    elif cmd == 'users':
        conn = db.connect()
        for r in conn.execute('''SELECT u.email, u.name, u.email_verified, f.name AS family, m.role FROM users u
                                 LEFT JOIN members m ON m.user_id = u.id LEFT JOIN families f ON f.id = m.family_id ORDER BY f.id'''):
            print(f"{r['email']:<35} {r['name']:<20} {'✓' if r['email_verified'] else ' '}  {r['family'] or '-'} ({r['role'] or '-'})")
    elif cmd == 'verify':
        return verify()
    elif cmd == 'reindex':
        with db.transaction() as conn:
            conn.execute('DELETE FROM documents_fts')
            rows = conn.execute('SELECT * FROM documents').fetchall()
            for r in rows:
                search.index(conn, r)
        print(f'{len(rows)} documents indexed')
    elif cmd == 'export-key':
        with open(storage.key_path(), 'rb') as f:
            print(base64.b64encode(f.read()).decode())
    elif cmd == 'import-key' and len(argv) == 3:
        key = base64.b64decode(argv[2])
        if len(key) != 32:
            print('The key must be 32 bytes (base64 of 44 characters)')
            return 1
        if os.path.exists(storage.key_path()):
            print(f'{storage.key_path()} already exists: move it away first if you really want to replace it')
            return 1
        fd = os.open(storage.key_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(key)
        print('Key written to', storage.key_path())
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

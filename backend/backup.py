"""Database backups: consistent copies (SQLite backup API) with rotation."""
import datetime
import os
import re
import sqlite3
import threading
import time

import db

BACKUP_DIR = os.path.join(db.DATA_DIR, 'backups')
KEEP = int(os.environ.get('PATRACK_BACKUP_KEEP', '30'))
VALID_NAME = re.compile(r'^[\w.-]+\.db$')


def create_backup(prefix='auto'):
    if not os.path.exists(db.DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"{prefix}-{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    dest = sqlite3.connect(os.path.join(BACKUP_DIR, name))
    src = sqlite3.connect(db.DB_PATH)
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()
    _rotate(prefix)
    return name


def _rotate(prefix):
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(prefix + '-') and f.endswith('.db'))
    for f in files[:-KEEP]:
        os.remove(os.path.join(BACKUP_DIR, f))


def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for f in os.listdir(BACKUP_DIR):
        if VALID_NAME.match(f):
            st = os.stat(os.path.join(BACKUP_DIR, f))
            out.append({'name': f, 'size': st.st_size,
                        'created_at': datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')})
    out.sort(key=lambda b: b['created_at'], reverse=True)
    return out


def backup_path(name):
    if not VALID_NAME.match(name or ''):
        return None
    p = os.path.join(BACKUP_DIR, name)
    return p if os.path.isfile(p) else None


def _last_auto():
    files = [b for b in list_backups() if b['name'].startswith('auto-')]
    return datetime.datetime.fromisoformat(files[0]['created_at']) if files else None


def start_scheduler(interval_hours=24):
    """Background thread making an automatic backup every `interval_hours` (checked hourly)."""
    def loop():
        while True:
            try:
                last = _last_auto()
                if not last or datetime.datetime.now() - last >= datetime.timedelta(hours=interval_hours):
                    create_backup('auto')
            except Exception as e:  # must never stop the app
                print(f'[backup] error: {e}', flush=True)
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name='backup-scheduler').start()

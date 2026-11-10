"""SQLite database: connection and schema."""
import os
import sqlite3
from contextlib import contextmanager

DATA_DIR = os.environ.get('PATRACK_DATA', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'patrack.db')

SCHEMA_VERSION = 1

# Values stored in the database. They are stable keys: the UI translates them.
CATEGORIES = ['identity', 'health', 'child', 'home', 'car', 'tax', 'work', 'purchases', 'bank', 'insurance', 'other']
ROLES = ['admin', 'member']
# ready = processed; processing = waiting for/under OCR; review = "da sistemare" (something went wrong or is missing)
DOC_STATUSES = ['processing', 'ready', 'review']
# queued → processing → done | error; duplicate = same file already in the archive (nothing was stored)
IMPORT_STATUSES = ['queued', 'processing', 'done', 'error', 'duplicate']
IMPORT_SOURCES = ['upload', 'scan', 'shortcut', 'email', 'api']
TRASH_DAYS = 30

SCHEMA = '''
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    session_version INTEGER NOT NULL DEFAULT 1,
    consent_at TEXT,
    language TEXT NOT NULL DEFAULT 'it',
    totp_secret TEXT,
    totp_pending TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS members (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (family_id, user_id)
);
CREATE TABLE IF NOT EXISTS identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (provider, subject)
);
CREATE TABLE IF NOT EXISTS tokens (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER REFERENCES families(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Who documents are about: every member (user_id set) plus people without an account (kids, grandparents…)
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    birth_date DATE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_people_user ON people(family_id, user_id);
-- One document = one original file, kept byte for byte (encrypted at rest) in DATA_DIR/files
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT,                              -- NULL = not chosen yet
    doc_type TEXT NOT NULL DEFAULT '',          -- free: "Bolletta luce", "Referto", "Carta d'identità"…
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,   -- NULL = the whole family
    doc_date DATE,                              -- date written on the document
    expiry_date DATE,
    amount_cents INTEGER,
    issuer TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'processing',
    review_reason TEXT,                          -- why it is "da sistemare" (a message key)
    ocr_text TEXT NOT NULL DEFAULT '',
    text_source TEXT,                            -- pdf (embedded text) | ocr | mixed | email | text | NULL
    pages INTEGER,
    -- the original file
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    preview_name TEXT,                           -- JPEG of the first page (encrypted too)
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_family ON documents(family_id, deleted_at, doc_date);
CREATE INDEX IF NOT EXISTS idx_docs_sha ON documents(family_id, sha256);
-- Full-text index (rowid = documents.id), kept in sync by search.index()
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, doc_type, issuer, notes, body, tokenize = 'unicode61 remove_diacritics 2'
);
-- Import queue: every file received, from any source, with its outcome. Never deleted silently.
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,                                  -- message key of the failure
    error_detail TEXT,                           -- technical detail, for the log/tooltip
    attempts INTEGER NOT NULL DEFAULT 0,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    duplicate_of INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    batch TEXT,                                  -- files that arrived together (one email)
    email_from TEXT,
    email_subject TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0,        -- hidden from the queue by the user
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_imports_family ON imports(family_id, dismissed, id);
CREATE INDEX IF NOT EXISTS idx_imports_status ON imports(status);
-- Extra addresses a user may forward documents from (their own email always works)
CREATE TABLE IF NOT EXISTS mail_senders (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Emails already handled (by Message-ID), so a restart never imports one twice
CREATE TABLE IF NOT EXISTS mail_seen (
    message_id TEXT PRIMARY KEY,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Personal API tokens (the iPhone Shortcut, scripts): only the hash is stored
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Two-step verification: single-use recovery codes (hashed)
CREATE TABLE IF NOT EXISTS recovery_codes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    used_at TEXT,
    PRIMARY KEY (user_id, hash)
);
'''


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def transaction():
    """Connection that commits on success and rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bump(conn, family_id):
    """Something changed in the family: clients polling /api/sync reload."""
    if family_id:
        conn.execute('UPDATE families SET version = version + 1 WHERE id = ?', (family_id,))


def create_family(conn, name, language='it'):
    return conn.execute('INSERT INTO families (name) VALUES (?)', (name,)).lastrowid


def ensure_person(conn, family_id, user_id, name):
    """Every member is also a person documents can be about."""
    conn.execute('INSERT OR IGNORE INTO people (family_id, user_id, name) VALUES (?,?,?)', (family_id, user_id, name))


def people(conn, family_id):
    return [dict(r) for r in conn.execute(
        'SELECT id, name, user_id, birth_date FROM people WHERE family_id = ? ORDER BY user_id IS NULL, name COLLATE NOCASE',
        (family_id,))]


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # weHub link (see hub.py): which weHub family/user/person each row is, NULL = not managed there
        for table, column in (('families', 'hub_id'), ('families', 'hub_version'), ('users', 'hub_id'), ('people', 'hub_id')):
            if column not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} INTEGER')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_families_hub ON families(hub_id)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_hub ON users(hub_id)')
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        conn.execute('PRAGMA journal_mode = WAL')
        # Work interrupted by a restart goes back in the queue
        conn.execute("UPDATE imports SET status = 'queued' WHERE status = 'processing'")
        conn.commit()
    finally:
        conn.close()

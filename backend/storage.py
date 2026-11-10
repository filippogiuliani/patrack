"""File storage, encrypted at rest (AES-256-GCM).

Each file lives in DATA_DIR/files/<2 chars>/<random name>.bin as: b'PTK1' + 12-byte nonce + ciphertext + tag.
The stored name is bound as associated data, so a file cannot be swapped for another one unnoticed.

The key is 32 random bytes in PATRACK_KEY_FILE (default DATA_DIR/.file_key), created on first start.
Without it the files cannot be read: keep a copy somewhere else (the NAS backup script includes it, inside the
encrypted Borg repository)."""
import os
import secrets
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import db

MAGIC = b'PTK1'
_key = None


def files_dir():
    return os.path.join(db.DATA_DIR, 'files')


def key_path():
    return os.environ.get('PATRACK_KEY_FILE') or os.path.join(db.DATA_DIR, '.file_key')


def _load_key():
    global _key
    if _key is None:
        path = key_path()
        if not os.path.exists(path):
            if os.path.isdir(files_dir()) and any(os.scandir(files_dir())):
                # Files exist but the key is gone: never create a new key over them
                raise RuntimeError(f'Encryption key {path} is missing but encrypted files exist: restore the key')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(secrets.token_bytes(32))
            print(f'[storage] new encryption key created in {path}: keep a copy of it', flush=True)
        with open(path, 'rb') as f:
            k = f.read()
        if len(k) != 32:
            raise RuntimeError(f'Encryption key {path} is not 32 bytes long')
        _key = k
    return _key


def reset_key_cache():
    global _key
    _key = None


def _path(stored_name):
    if not stored_name or '/' in stored_name or '..' in stored_name:
        raise ValueError('invalid stored name')
    return os.path.join(files_dir(), stored_name[:2], stored_name)


def put(data: bytes) -> str:
    """Encrypt and write `data`; returns the stored name. The write is atomic (temp file + rename)."""
    name = uuid.uuid4().hex + '.bin'
    path = _path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nonce = secrets.token_bytes(12)
    blob = MAGIC + nonce + AESGCM(_load_key()).encrypt(nonce, data, name.encode())
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return name


def get(stored_name: str) -> bytes:
    with open(_path(stored_name), 'rb') as f:
        blob = f.read()
    if blob[:4] != MAGIC:
        raise ValueError('not a paTrack file')
    return AESGCM(_load_key()).decrypt(blob[4:16], blob[16:], stored_name.encode())


def delete(stored_name):
    try:
        os.remove(_path(stored_name))
    except FileNotFoundError:
        pass


def exists(stored_name):
    return os.path.isfile(_path(stored_name))


def check_key():
    """Called at start-up: fails loudly if the key is missing while files exist."""
    _load_key()

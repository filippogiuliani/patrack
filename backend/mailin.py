"""Import by email: forward a message to the archive address and its attachments become documents.

paTrack reads a dedicated mailbox over IMAP every minute (no port to open on the server):
  PATRACK_INBOX_ADDRESS     the address people forward to, shown in the app (e.g. archivio@example.com)
  PATRACK_IMAP_HOST / _PORT (993) / _USER / _PASSWORD / _FOLDER (INBOX)
  PATRACK_IMAP_DONE_FOLDER  optional: handled messages are moved there (otherwise they are only marked as read)
  PATRACK_IMAP_REQUIRE_AUTH 1 (default): accept only messages whose sender passed SPF or DKIM, according to the
                            Authentication-Results header added by the receiving mail server

Who can send: the email address of a paTrack account, or one of the extra addresses a user added. The documents go
to that user's (first) family. Unknown senders are ignored and get no answer (no backscatter). Known senders get one
email back when every file of the message has an outcome: what was imported, what was a duplicate, what failed."""
import datetime
import email.utils
import imaplib
import os
import re
import threading
import time
import traceback
from email import policy
from email.parser import BytesParser

import db
import i18n
import imports
from famkit import mail

ADDRESS = os.environ.get('PATRACK_INBOX_ADDRESS', '').strip()
HOST = os.environ.get('PATRACK_IMAP_HOST', '')
PORT = int(os.environ.get('PATRACK_IMAP_PORT', '993'))
USER = os.environ.get('PATRACK_IMAP_USER', '')
PASSWORD = os.environ.get('PATRACK_IMAP_PASSWORD', '')
FOLDER = os.environ.get('PATRACK_IMAP_FOLDER', 'INBOX')
DONE_FOLDER = os.environ.get('PATRACK_IMAP_DONE_FOLDER', '')
REQUIRE_AUTH = os.environ.get('PATRACK_IMAP_REQUIRE_AUTH', '1') not in ('0', 'off', 'false', 'no')
INTERVAL = int(os.environ.get('PATRACK_IMAP_INTERVAL', '60'))

# Small inline images are logos and signatures, not documents
MIN_INLINE_IMAGE = 40 * 1024
SKIP_TYPES = {'application/pkcs7-signature', 'application/x-pkcs7-signature', 'application/pgp-signature',
              'application/ms-tnef', 'text/calendar'}

_status = {'last_check': None, 'last_ok': None, 'last_error': None, 'imported': 0}


def enabled():
    return bool(HOST and USER and PASSWORD)


def status():
    return {'address': ADDRESS or None, 'enabled': enabled(), **_status}


# ---------- Parsing ----------

def sender_of(msg):
    return email.utils.parseaddr(str(msg.get('From', '')))[1].lower()


def authenticated(msg):
    """True when the receiving server says SPF or DKIM passed (and DMARC did not fail).
    Only the topmost Authentication-Results header counts: it is the one added by our own mail server."""
    headers = msg.get_all('Authentication-Results') or []
    if not headers:
        return not REQUIRE_AUTH
    top = str(headers[0]).lower()
    if re.search(r'\bdmarc=fail\b', top):
        return False
    return bool(re.search(r'\b(dkim|spf)=pass\b', top)) or not REQUIRE_AUTH


def attachments(msg):
    """[(file name, bytes)] of the documents in the message, forwarded messages included."""
    out = []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_type() in SKIP_TYPES:
            continue
        name = part.get_filename()
        disposition = (part.get_content_disposition() or '').lower()
        ctype = part.get_content_type()
        if not name and disposition != 'attachment':
            continue  # the body of the message (or of a forwarded one)
        data = part.get_payload(decode=True) or b''
        if ctype.startswith('image/') and disposition != 'attachment' and part.get('Content-ID') and len(data) < MIN_INLINE_IMAGE:
            continue
        if not name:
            ext = {'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png'}.get(ctype, '')
            name = f'allegato{len(out) + 1}{ext}'
        out.append((name, data))
    return out


def _user_for(conn, address):
    r = conn.execute('''SELECT u.id, u.email, u.name, u.language FROM users u WHERE u.email = ?
                        UNION SELECT u.id, u.email, u.name, u.language FROM mail_senders s JOIN users u ON u.id = s.user_id
                        WHERE s.email = ?''', (address, address)).fetchone()
    if not r:
        return None, None
    fam = conn.execute('SELECT family_id FROM members WHERE user_id = ? ORDER BY created_at LIMIT 1', (r['id'],)).fetchone()
    return r, (fam['family_id'] if fam else None)


def handle_message(raw: bytes):
    """Import one email. Returns an outcome string (also stored in mail_seen)."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = str(msg.get('Message-ID') or '').strip() or None
    with db.transaction() as conn:
        if message_id and conn.execute('SELECT 1 FROM mail_seen WHERE message_id = ?', (message_id,)).fetchone():
            return 'already_seen'
    address = sender_of(msg)
    subject = str(msg.get('Subject') or '').strip()
    with db.transaction() as conn:
        user, family_id = _user_for(conn, address)
        if not user or not family_id:
            outcome = 'unknown_sender'
        elif not authenticated(msg):
            outcome = 'not_authenticated'
        else:
            outcome = None
        if outcome:
            if message_id:
                conn.execute('INSERT OR IGNORE INTO mail_seen (message_id, outcome) VALUES (?, ?)', (message_id, outcome))
    if outcome:
        print(f'[mailin] message from {address or "?"} ignored: {outcome}', flush=True)
        if outcome == 'not_authenticated':
            # It may be forged, but the answer goes to the real owner of the address, who is one of us
            mail.send(user['email'], *i18n.email('mail_rejected', user['language'], subject=subject or '-'))
        return outcome

    files = attachments(msg)
    batch = imports.new_batch()
    with db.transaction() as conn:
        if files:
            for name, data in files:
                imports.intake(conn, family_id, user['id'], 'email', name, data, batch=batch, email_from=address,
                               email_subject=subject)
        else:
            # No attachments: the message itself is the document (a receipt in the body, a booking…)
            imports.intake(conn, family_id, user['id'], 'email', (subject or 'email')[:80] + '.eml', raw, batch=batch,
                           email_from=address, email_subject=subject, title=subject or None)
        if message_id:
            conn.execute('INSERT OR IGNORE INTO mail_seen (message_id, outcome) VALUES (?, ?)', (message_id, f'imported:{batch}'))
    _status['imported'] += max(1, len(files))
    imports.wake()
    imports.batch_finished(batch)  # all duplicates/errors already: answer now
    return 'imported'


def send_summary(batch):
    """One email to the sender with the outcome of every file of their message."""
    with db.transaction() as conn:
        rows = conn.execute('''SELECT i.file_name, i.status, i.error, i.email_from, i.email_subject, i.user_id,
                                      d.status AS doc_status, d.review_reason, d.title
                               FROM imports i LEFT JOIN documents d ON d.id = i.document_id WHERE i.batch = ? ORDER BY i.id''',
                            (batch,)).fetchall()
        if not rows or not rows[0]['email_from']:
            return
        claimed = conn.execute("UPDATE imports SET batch = 'sent:' || batch WHERE batch = ?", (batch,)).rowcount
        u = conn.execute('SELECT language FROM users WHERE id = ?', (rows[0]['user_id'],)).fetchone()
    if not claimed:
        return  # already sent
    lang = u['language'] if u else i18n.DEFAULT
    lines = []
    for r in rows:
        if r['status'] == 'done':
            state = i18n.tr('imported', lang)
            if r['doc_status'] == 'review':
                state += ' – ' + i18n.tr('to fix', lang) + ': ' + i18n.reason(r['review_reason'], lang)
        elif r['status'] == 'duplicate':
            state = i18n.tr('already in the archive', lang)
        else:
            state = i18n.tr('error', lang) + ': ' + i18n.reason(r['error'], lang)
        lines.append(f'- {r["file_name"]}: {state}')
    from auth import BASE_URL
    mail.send(rows[0]['email_from'], *i18n.email('mail_summary', lang, subject=rows[0]['email_subject'] or '-',
                                                 lines='\n'.join(lines), link=f'{BASE_URL}/#/imports' if BASE_URL else ''))


# ---------- IMAP ----------

def check_mailbox():
    """Read the unread messages once. Errors are kept in the status shown on the Family page."""
    _status['last_check'] = datetime.datetime.now().isoformat(timespec='seconds')
    try:
        box = imaplib.IMAP4_SSL(HOST, PORT, timeout=60) if PORT == 993 else imaplib.IMAP4(HOST, PORT, timeout=60)
        if PORT != 993:
            box.starttls()
        try:
            box.login(USER, PASSWORD)
            typ, _ = box.select(FOLDER)
            if typ != 'OK':
                raise RuntimeError(f'folder {FOLDER} not found')
            typ, data = box.uid('SEARCH', None, 'UNSEEN')
            for uid in (data[0] or b'').split():
                typ, parts = box.uid('FETCH', uid, '(BODY.PEEK[])')
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw is None:
                    continue
                try:
                    handle_message(raw)
                except Exception:
                    # Leave it unread: it will be tried again at the next check, and the error is visible
                    traceback.print_exc()
                    _status['last_error'] = 'message_failed'
                    continue
                box.uid('STORE', uid, '+FLAGS', '(\\Seen)')
                if DONE_FOLDER:
                    if box.uid('COPY', uid, DONE_FOLDER)[0] == 'OK':
                        box.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
            if DONE_FOLDER:
                box.expunge()
        finally:
            try:
                box.logout()
            except Exception:
                pass
        _status['last_ok'] = _status['last_check']
        _status['last_error'] = None
    except Exception as e:
        _status['last_error'] = f'{type(e).__name__}: {e}'[:300]
        print(f'[mailin] {_status["last_error"]}', flush=True)


def start_poller():
    if not enabled():
        print('[mailin] email import off (PATRACK_IMAP_HOST/USER/PASSWORD not set)', flush=True)
        return

    def loop():
        while True:
            check_mailbox()
            time.sleep(INTERVAL)

    threading.Thread(target=loop, daemon=True, name='mail-import').start()
    print(f'[mailin] reading {USER}@{HOST}/{FOLDER} every {INTERVAL}s', flush=True)

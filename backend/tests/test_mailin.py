"""Import by email: who may send, what becomes a document, the summary sent back."""
import mailin
from conftest import ok, run_queue
from samples import email_with, pdf_with_text


def pdf(name='bolletta.pdf', text='Bolletta acqua'):
    return (name, pdf_with_text([text]), 'application/pdf')


def test_attachments_become_documents(family, outbox):
    outbox.clear()
    raw = email_with([pdf('a.pdf', 'Prima'), pdf('b.pdf', 'Seconda')], subject='Fwd: bollette')
    assert mailin.handle_message(raw) == 'imported'
    q = ok(family.c.get('/api/imports'))['items']
    assert {i['file_name'] for i in q} == {'a.pdf', 'b.pdf'} and all(i['source'] == 'email' for i in q)
    assert q[0]['email_subject'] == 'Fwd: bollette' and q[0]['email_from'] == 'fil@example.com'
    assert not outbox  # the summary waits for the outcome
    run_queue()
    assert ok(family.c.get('/api/documents?q=seconda'))['total'] == 1
    (to, subject, body), = outbox
    assert to == 'fil@example.com' and 'bollette' in subject and 'a.pdf: importato' in body and 'b.pdf: importato' in body
    # The same email again (e.g. after a restart) is not imported twice
    assert mailin.handle_message(raw) == 'already_seen'


def test_duplicates_and_errors_in_the_summary(family, outbox):
    outbox.clear()
    data = pdf_with_text(['Doppio'])
    family.upload(data)
    raw = email_with([('doppio.pdf', data, 'application/pdf'), ('vuoto.pdf', b'', 'application/pdf')], message_id='<m2@x>')
    mailin.handle_message(raw)
    # Nothing to process: the answer goes at once
    (_, _, body), = outbox
    assert 'doppio.pdf: già in archivio' in body and 'vuoto.pdf: errore: il file è vuoto' in body


def test_email_without_attachments_is_kept_as_message(family, outbox):
    mailin.handle_message(email_with(subject='Conferma prenotazione visita', body='Visita cardiologica il 3 dicembre'))
    run_queue()
    d = ok(family.c.get('/api/documents?q=cardiologica'))['items'][0]
    assert d['title'] == 'Conferma prenotazione visita' and d['mime'] == 'message/rfc822'


def test_inline_logos_are_skipped(family):
    mailin.handle_message(email_with([pdf()], inline_logo=True))
    assert [i['file_name'] for i in ok(family.c.get('/api/imports'))['items']] == ['bolletta.pdf']


def test_unknown_sender_is_ignored_silently(family, outbox):
    outbox.clear()
    assert mailin.handle_message(email_with([pdf()], sender='spam@evil.example')) == 'unknown_sender'
    assert ok(family.c.get('/api/imports'))['items'] == [] and not outbox


def test_extra_sender_addresses(family, client):
    ok(family.c.post('/api/account/mail-senders', json={'email': 'Fil.Work@Company.example'}), 201)
    assert family.c.post('/api/account/mail-senders', json={'email': 'fil.work@company.example'}).status_code == 409
    assert family.c.post('/api/account/mail-senders', json={'email': 'sara@example.com'}).status_code == 201
    assert mailin.handle_message(email_with([pdf()], sender='fil.work@company.example')) == 'imported'
    assert ok(family.c.get('/api/family'))['mail_senders'] == ['fil.work@company.example', 'sara@example.com']
    ok(family.c.delete('/api/account/mail-senders/fil.work@company.example'))
    assert mailin.handle_message(email_with([pdf()], sender='fil.work@company.example', message_id='<m9@x>')) == 'unknown_sender'


def test_forged_sender_is_rejected(family, outbox):
    outbox.clear()
    raw = email_with([pdf()], auth='spf=fail smtp.mailfrom=fil@example.com; dkim=none')
    assert mailin.handle_message(raw) == 'not_authenticated'
    assert ok(family.c.get('/api/imports'))['items'] == []
    (to, subject, _), = outbox
    assert to == 'fil@example.com' and 'non importata' in subject
    raw = email_with([pdf()], auth='dkim=pass header.d=example.com; dmarc=fail', message_id='<m3@x>')
    assert mailin.handle_message(raw) == 'not_authenticated'
    # Without the header, accepted only when the check is turned off
    assert mailin.handle_message(email_with([pdf()], auth=None, message_id='<m4@x>')) == 'not_authenticated'


def test_check_can_be_turned_off(family, monkeypatch):
    monkeypatch.setattr(mailin, 'REQUIRE_AUTH', False)
    assert mailin.handle_message(email_with([pdf()], auth=None)) == 'imported'


def test_partner_email_goes_to_the_shared_family(family):
    p = family.add_partner()
    mailin.handle_message(email_with([pdf()], sender='sara@example.com'))
    run_queue()
    assert ok(family.c.get('/api/documents'))['total'] == 1
    assert ok(p.get('/api/imports'))['items'][0]['user_name'] == 'Sara'


class FakeIMAP:
    """Just enough of imaplib for check_mailbox()."""

    def __init__(self, messages):
        self.messages = dict(messages)
        self.seen = set()

    def __call__(self, *args, **kwargs):
        return self

    def login(self, user, password):
        pass

    def select(self, folder):
        return 'OK', [b'1']

    def uid(self, cmd, *args):
        if cmd == 'SEARCH':
            return 'OK', [b' '.join(k for k in self.messages if k not in self.seen)]
        if cmd == 'FETCH':
            return 'OK', [(b'1 (BODY[] {n}', self.messages[args[0]]), b')']
        if cmd == 'STORE':
            self.seen.add(args[0])
            return 'OK', []
        return 'OK', []

    def logout(self):
        pass


def test_mailbox_check(family, monkeypatch):
    fake = FakeIMAP({b'7': email_with([pdf()]), b'8': email_with([pdf('c.pdf', 'altro')], message_id='<m8@x>')})
    monkeypatch.setattr(mailin.imaplib, 'IMAP4_SSL', fake)
    monkeypatch.setattr(mailin, 'HOST', 'imap.example.com')
    mailin.check_mailbox()
    assert fake.seen == {b'7', b'8'} and mailin._status['last_error'] is None
    assert len(ok(family.c.get('/api/imports'))['items']) == 2


def test_mailbox_errors_are_visible(family, monkeypatch):
    def refuse(*a, **k):
        raise OSError('connection refused')
    monkeypatch.setattr(mailin.imaplib, 'IMAP4_SSL', refuse)
    mailin.check_mailbox()
    assert 'connection refused' in ok(family.c.get('/api/family'))['inbox']['last_error']

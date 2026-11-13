"""Server-side translations: error messages, emails and the reasons shown in the import queue.
Source texts are in English; Italian translations below."""
import re

from flask import g, has_request_context, request

LANGUAGES = ['it', 'en']
DEFAULT = 'it'


def normalize(value):
    v = str(value or '').lower()[:2]
    return v if v in LANGUAGES else None


def language():
    """Request language: user profile > X-Language header (from the frontend) > Accept-Language > default."""
    if not has_request_context():
        return DEFAULT
    user = getattr(g, 'user', None)
    if user and normalize(user.get('language')):
        return user['language']
    return (normalize(request.headers.get('X-Language'))
            or request.accept_languages.best_match(LANGUAGES)
            or DEFAULT)


IT = {
    'The family is managed in weHub': 'La famiglia si gestisce in weHub',
    'You cannot use this app: ask the family admin in weHub': "Non puoi usare quest'app: chiedi all'amministratore della famiglia in weHub",
    'weHub is not reachable, please try again in a moment': 'weHub non è raggiungibile, riprova tra poco',
    'To sign up you must accept the privacy notice': "Per registrarti devi accettare l'informativa privacy",
    "You're the only member: to delete the family, delete your account": "Sei l'unico membro: per eliminare la famiglia elimina l'account",
    'Sign in or sign up to accept': 'Accedi o registrati per accettare',
    'Sign-in failed, please try again': 'Accesso non riuscito, riprova',
    'Sign-in required': 'Accesso richiesto',
    'Sign-up expired: please try again': 'Registrazione scaduta: riprova',
    'Invalid email': 'Email non valida',
    'Wrong email or password': 'Email o password errati',
    'An account with this email already exists': 'Esiste già un account con questa email',
    'Family not found': 'Famiglia non trovata',
    'Name is required': 'Il nome è obbligatorio',
    'The provider did not return an identifier': 'Il provider non ha fornito un identificativo',
    'The provider did not return a verified email address': 'Il provider non ha fornito un indirizzo email verificato',
    "Set a password first, otherwise you couldn't sign in anymore": 'Imposta prima una password, altrimenti non potresti più accedere',
    'Invalid or expired invitation': 'Invito non valido o scaduto',
    'Sign-up is by invitation only': 'La registrazione è possibile solo su invito',
    'Invalid or expired link': 'Link non valido o scaduto',
    'Member not found': 'Membro non trovato',
    'No file uploaded': 'Nessun file caricato',
    'No family associated': 'Nessuna famiglia associata',
    'No sign-up in progress': 'Nessuna registrazione in corso',
    'Origin not allowed': 'Origine non consentita',
    'Current password is wrong': 'Password attuale errata',
    'Password too long': 'Password troppo lunga',
    'Provider not configured': 'Provider non configurato',
    'This account is already linked to another user': 'Questo account è già collegato a un altro utente',
    'Only the family admin can do this': "Solo l'amministratore della famiglia può farlo",
    'Too many attempts, try again in a few minutes': 'Troppi tentativi, riprova tra qualche minuto',
    'Type your email to confirm': 'Scrivi la tua email per confermare',
    'Invalid request (JSON expected)': 'Richiesta non valida (atteso JSON)',
    'invalid family_id': 'family_id non valido',
    "{name}'s family": 'Famiglia di {name}',
    # People
    'There is already someone with this name': "C'è già qualcuno con questo nome",
    'Too many people': 'Troppe persone',
    'Person not found': 'Persona non trovata',
    'A member cannot be removed from here': 'Un membro non si elimina da qui',
    'Invalid person': 'Persona non valida',
    'This address is already in use': 'Questo indirizzo è già in uso',
    'Too many addresses': 'Troppi indirizzi',
    # Documents and imports
    'Document not found': 'Documento non trovato',
    'Import not found': 'Import non trovato',
    'No preview': 'Nessuna anteprima',
    'Invalid category': 'Categoria non valida',
    'Invalid amount': 'Importo non valido',
    'Invalid reminder': 'Promemoria non valido',
    'Invalid kind': 'Tipo non valido',
    'No documents for the tax return in this year': "Nessun documento per la dichiarazione in quest'anno",
    'Medical expenses': 'Spese sanitarie', 'School and nursery': 'Scuola e asilo nido', 'Mortgage interest': 'Interessi del mutuo',
    'Life and accident insurance': 'Assicurazioni vita e infortuni', "Children's sport": 'Sport dei ragazzi', 'Vet': 'Veterinario',
    'Home works and bonuses': 'Lavori in casa e bonus', 'Rent': 'Affitto', 'Donations': 'Donazioni', 'Other': 'Altro',
    'Kind': 'Tipo', 'Person': 'Persona', 'Date': 'Data', 'Document': 'Documento', 'Issuer': 'Emesso da',
    'Amount (€)': 'Importo (€)', 'File': 'File', 'Whole family': 'Tutta la famiglia', 'summary': 'riepilogo',
    'missing file': 'file mancante',
    'Invalid file': 'File non valido',
    'The file could not be archived': 'Non è stato possibile archiviare il file',
    'This document is already in paTrack with its own deadline': 'Questo documento è già in paTrack con la sua scadenza',
    'This family is not linked to weHub': 'Questa famiglia non è collegata a weHub',
    'You do not use paTrack in this family': 'Non usi paTrack in questa famiglia',
    'Already being processed': 'Già in elaborazione',
    'Move it to the trash first': 'Spostalo prima nel cestino',
    'Not a duplicate': 'Non è un duplicato',
    'The file was not received: send it again': 'Il file non è arrivato: invialo di nuovo',
    'Request Entity Too Large': 'File troppo grande',
    'imported': 'importato',
    'to fix': 'da sistemare',
    'already in the archive': 'già in archivio',
    'error': 'errore',
    # Security and integrations
    'Not allowed with an API token': 'Non consentito con un token API',
    'Sign-in with a password is disabled: use one of the providers': "L'accesso con password è disattivato: usa uno dei provider",
    'Sign-up with a password is disabled: use one of the providers': 'La registrazione con password è disattivata: usa uno dei provider',
    'Sign-in expired: please enter your password again': 'Accesso scaduto: inserisci di nuovo la password',
    'Wrong code': 'Codice errato',
    'Start the setup again': 'Ricomincia la configurazione',
    'Wrong code: check the time on your phone and try again': "Codice errato: controlla l'ora del telefono e riprova",
    'Wrong code or password': 'Codice o password errati',
    'Two-step verification is off': 'La verifica in due passaggi non è attiva',
    'Too many tokens': 'Troppi token',
    'date': 'data', 'doc_date': 'data del documento', 'expiry_date': 'scadenza', 'birth_date': 'data di nascita',
}

IT_PATTERNS = [
    (r'^Password must be at least (\d+) characters$', r'La password deve avere almeno \1 caratteri'),
    (r'^(.+): invalid date$', r'\1: data non valida'),
    (r'^(.+): invalid time$', r'\1: ora non valida'),
]

MESSAGES = {'it': (IT, IT_PATTERNS)}


def tr(text, lang=None, **values):
    lang = lang or language()
    if lang in MESSAGES:
        dictionary, patterns = MESSAGES[lang]
        if text in dictionary:
            text = dictionary[text]
        else:
            for pattern, template in patterns:
                if m := re.match(pattern, text):
                    parts = [dictionary.get(p, p) for p in m.groups()]
                    text = re.sub(r'\\(\d)', lambda ref: parts[int(ref.group(1)) - 1], template)
                    break
    return text.format(**values) if values else text


# Why a document is "da sistemare" or an import failed (keys stored in the database)
REASONS = {
    'en': {
        'empty_file': 'the file is empty', 'too_large': 'the file is too large', 'storage_failed': 'the file could not be saved',
        'file_unreadable': 'the saved file could not be read', 'document_missing': 'the document was deleted',
        'ocr_unavailable': 'text recognition (OCR) is not available on the server', 'ocr_timeout': 'text recognition took too long',
        'ocr_failed': 'text recognition failed', 'processing_failed': 'unexpected error while reading the file',
        'pdf_protected': 'the PDF is password protected', 'pdf_damaged': 'the PDF is damaged',
        'image_unreadable': 'the image cannot be opened', 'unsupported_format': 'no text or preview for this kind of file',
        'no_text': 'no text found', 'partially_read': 'only the first pages were read',
    },
    'it': {
        'empty_file': 'il file è vuoto', 'too_large': 'il file è troppo grande', 'storage_failed': 'il file non è stato salvato',
        'file_unreadable': 'il file salvato non si legge', 'document_missing': 'il documento è stato eliminato',
        'ocr_unavailable': 'il riconoscimento del testo (OCR) non è disponibile sul server',
        'ocr_timeout': 'il riconoscimento del testo ha impiegato troppo', 'ocr_failed': 'il riconoscimento del testo non è riuscito',
        'processing_failed': 'errore imprevisto durante la lettura del file', 'pdf_protected': 'il PDF è protetto da password',
        'pdf_damaged': 'il PDF è danneggiato', 'image_unreadable': "l'immagine non si apre",
        'unsupported_format': 'nessun testo né anteprima per questo tipo di file', 'no_text': 'nessun testo trovato',
        'partially_read': 'sono state lette solo le prime pagine',
    },
}


def reason(key, lang=None):
    return REASONS.get(lang or language(), REASONS['en']).get(key or '', key or '')


EMAILS = {
    'verify': {
        'it': ('Conferma il tuo indirizzo email – paTrack',
               'Ciao!\n\nConferma il tuo indirizzo email aprendo questo link:\n{link}\n\n'
               'Il link vale 3 giorni. Se non ti sei registrato su paTrack ignora questo messaggio.'),
        'en': ('Confirm your email address – paTrack',
               'Hi!\n\nConfirm your email address by opening this link:\n{link}\n\n'
               "The link is valid for 3 days. If you didn't sign up for paTrack, ignore this message."),
    },
    'reset': {
        'it': ('Reimposta la password – paTrack',
               'Per scegliere una nuova password apri questo link (vale 2 ore):\n{link}\n\n'
               'Se non hai chiesto tu il cambio password ignora questo messaggio.'),
        'en': ('Reset your password – paTrack',
               'To choose a new password open this link (valid for 2 hours):\n{link}\n\n'
               "If you didn't request a password change, ignore this message."),
    },
}


EMAILS['mail_summary'] = {
    'it': ('paTrack: {subject}', 'Ecco cosa è successo agli allegati della tua email "{subject}":\n\n{lines}\n\n{link}'),
    'en': ('paTrack: {subject}', 'Here is what happened to the attachments of your email "{subject}":\n\n{lines}\n\n{link}'),
}
EMAILS['mail_rejected'] = {
    'it': ('paTrack: email non importata',
           'Abbiamo ricevuto un\'email dal tuo indirizzo ("{subject}") ma il server di posta non ha potuto verificare che '
           'sia partita davvero da te (SPF/DKIM), quindi non l\'abbiamo importata.\n\nSe l\'hai mandata tu, '
           'carica gli allegati dall\'app. Se non sei stato tu, qualcuno sta usando il tuo indirizzo: non serve fare altro.'),
    'en': ('paTrack: email not imported',
           'We received an email from your address ("{subject}") but the mail server could not verify that it really came '
           'from you (SPF/DKIM), so it was not imported.\n\nIf you sent it, upload the attachments from the app. '
           'If you did not, someone is using your address: nothing else to do.'),
}


def email(kind, lang, **values):
    subject, text = EMAILS[kind].get(lang) or EMAILS[kind][DEFAULT]
    return subject.format(**values), text.format(**values)

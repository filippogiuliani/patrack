// Privacy notice texts, one entry per language: a draft banner, sections [title, html] and the "last updated" line.
// DRAFT: for a private family instance this is mostly a formality; if you open the app to others, complete the
// fields in [SQUARE BRACKETS] and have it reviewed. The html strings are written by the developers only (never user input).
export default {
  it: {
    draft: 'Bozza – da completare prima di aprire l\'app ad altre persone.',
    sections: [
      ['Titolare del trattamento', '[NOME], [INDIRIZZO], email: [EMAIL DI CONTATTO].'],
      ['Quali dati trattiamo', "Dati dell'account (nome, email, password cifrata o identificativo del provider di accesso) e i documenti che carichi, con il testo letto da essi e i dati che inserisci (categoria, persona, date, importi, note). I documenti possono contenere <b>dati relativi alla salute</b>, anche di minori, e dati economici e fiscali (art. 9 GDPR): li trattiamo solo sulla base del tuo consenso esplicito, che dai alla registrazione e puoi revocare eliminando l'account."],
      ['Perché li trattiamo', 'Solo per fornirti il servizio: conservare i documenti, renderli ricercabili e condividerli con i membri della famiglia che inviti tu. Il testo dei documenti viene letto sul nostro server; non lo inviamo a servizi esterni. Non vendiamo i dati e non li usiamo per pubblicità.'],
      ['Dove sono conservati e per quanto', 'Sul server [DOVE]; i file sono cifrati. Le copie di sicurezza, cifrate, sono conservate su [DOVE SONO I BACKUP]. Se importi via email, i messaggi passano dalla casella [FORNITORE EMAIL]. I dati restano finché hai un account; quando lo elimini vengono cancellati, e spariscono dalle copie di sicurezza entro [N] giorni. I documenti nel cestino sono eliminati dopo 30 giorni.'],
      ['I tuoi diritti', "Puoi in ogni momento correggere i tuoi dati, scaricare i tuoi documenti, eliminare l'account e tutti i dati, revocare il consenso e presentare reclamo al Garante per la protezione dei dati personali. Per qualsiasi richiesta: [EMAIL DI CONTATTO]."],
      ['Cookie', 'Usiamo un solo cookie tecnico per mantenerti collegato. Nessun cookie di profilazione o di terze parti.'],
    ],
    updated: 'Ultimo aggiornamento: [DATA]',
  },
  en: {
    draft: 'Draft – to be completed before opening the app to other people.',
    sections: [
      ['Data controller', '[NAME], [ADDRESS], email: [CONTACT EMAIL].'],
      ['What data we process', 'Account data (name, email, hashed password or sign-in provider identifier) and the documents you upload, with the text read from them and the details you enter (category, person, dates, amounts, notes). Documents may contain <b>health data</b>, including about children, and financial and tax data (art. 9 GDPR): we process them only with your explicit consent, given at sign-up and withdrawn by deleting your account.'],
      ['Why we process it', 'Only to provide the service: keeping the documents, making them searchable and sharing them with the family members you invite. The text of the documents is read on our server; it is not sent to outside services. We do not sell data or use it for advertising.'],
      ['Where it is stored and for how long', 'On the server [WHERE]; files are encrypted. Encrypted backups are kept at [WHERE BACKUPS ARE]. If you import by email, messages go through the mailbox at [EMAIL PROVIDER]. Data is kept while you have an account; when you delete it, it is erased, and it disappears from backups within [N] days. Documents in the trash are deleted after 30 days.'],
      ['Your rights', 'At any time you can correct your data, download your documents, delete your account and all data, withdraw consent and lodge a complaint with your data protection authority. For any request: [CONTACT EMAIL].'],
      ['Cookies', 'We use a single technical cookie to keep you signed in. No profiling or third-party cookies.'],
    ],
    updated: 'Last updated: [DATE]',
  },
};

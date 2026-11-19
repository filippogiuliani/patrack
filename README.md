# Pelican – family document archive

> **Disclaimer / Esclusione di responsabilità.** Pelican is provided *as is*, without any warranty: the authors accept **no responsibility or liability** for data loss, security problems, missed reminders, wrong information or any other consequence of using it. Read [DISCLAIMER.md](DISCLAIMER.md) before using it with real data. · Il software è fornito *così com'è*, senza garanzie: gli autori **non hanno alcuna responsabilità**. Leggi [DISCLAIMER.md](DISCLAIMER.md).

Every document of the family in one place: IDs and licences, health (reports, prescriptions, vaccinations), the kids
(paediatrician, nursery, school), home (contracts, mortgage, bills, condominium), car, taxes, work, purchases and
warranties, bank and insurance. Same stack, style and sign-in as **Kooka** and **Wallaby**.

Phase 1: import, archive, search. Phase 3: links with Kooka and Wallaby, the tax return view.

- **Import, never silently lost**
  - **Browser**: drag and drop anywhere in the window (dozens of files at once), file picker, paste.
  - **Scan** with the camera: the sheet's edges are found automatically (corners can be dragged), the page is
    straightened and cleaned up; several pages become one PDF. All in the browser.
  - **iPhone Share menu**: a Shortcut ("Save to Pelican") sends PDFs, photos, Mail/WhatsApp attachments and files with
    a personal key. Step-by-step instructions in the app (Family → From iPhone).
  - **Email**: forward a message to the archive address and its attachments are imported (no attachments: the email
    itself is kept). The sender gets an answer with the outcome of every file.
  - A **queue** shows every file with its state: queued, processing, done, done but *to fix* (and why), duplicate,
    error (and why) with **Retry**. Files that could not even leave the browser stay there with Retry.
  - **Duplicates** (same content, SHA-256) are reported, not stored twice; "keep it anyway" is one tap.
  - The **original** is stored byte for byte before anything else happens, encrypted at rest.
- **Reading**: text embedded in PDFs, **OCR** (Tesseract, Italian + English) for scans and photos (HEIC included),
  a preview of the first page. If reading fails the document is in the archive anyway, marked **to fix**.
- **Archive and search**: free text inside the documents ("bolletta luce marzo", "referto sangue Luca": words can
  match the text, a person, a category, a month or a year; Italian plurals and a few synonyms are handled), filters
  by person, category, year and expiry, sorting, highlighted extracts, a trash kept 30 days.
- **People**: every member is a person documents can be about, plus people without an account (kids, grandparents).

- **With the other family apps** (Wombat mode, only for people who use them):
  - *Remind me in Kooka* on a document with an expiry date: a Kooka deadline (reminder N days before, the person,
    a link back) kept in step with the document, removed with the trash; retried by itself when Kooka is down.
  - From a Kooka deadline, *Archive the document in Pelican*: the file comes here and keeps that deadline in step.
  - *Paediatrician's plan for Wallaby* on a child's document: listed on Wallaby's Plan page.
- **Tax return**: the year's expenses by kind (medical, school and nursery, mortgage interest, insurance, sport…) and
  person, with totals of the amounts written on the documents and what is missing an amount or a date; a ZIP with the
  originals (a folder per kind) and a CSV summary for the CAF. It collects, it does not compute deductions.

Coming next: automatic proposals (category, person, dates, amount, issuer) that learn from corrections (phase 2);
per-person sharing (phase 4).

- `backend/` – Flask API + SQLite (waitress, port 3002), OCR worker, IMAP reader
- `frontend/` – Svelte + Vite interface, built into the Docker image

> **Made with AI.** Like Kooka and Wallaby, this project was written by an AI assistant (Anthropic's Claude) and
> checked with automated tests; review it before exposing it to the internet.

## Running with Docker

The code shared with the other family apps is in the `backend/famkit` submodule
([famkit](https://github.com/filippogiuliani/famkit)): clone with
`git clone --recurse-submodules https://github.com/filippogiuliani/pelican.git`, or run `git submodule update --init` in a
clone made without it.

```sh
cp .env.example .env    # set PELICAN_URL, Pocket ID, SMTP, the archive mailbox
./rebuild.sh
```

Data lives in `./Pelican_data/` (mounted on `/app/data`):

| Path | What |
|---|---|
| `pelican.db` | database (documents' details, text read from them, queue, accounts) |
| `files/` | originals and previews, **encrypted** (AES-256-GCM) |
| `.file_key` | the encryption key. **Without it the files cannot be read.** |
| `backups/` | daily consistent copies of the database |
| `offsite.json` | outcome of the last NAS backup (written by the script below) |

Keep a copy of the key outside the server too: `docker exec pelican python manage.py export-key` prints it (base64),
e.g. for a password manager. `import-key` writes it back on a new server.

### Sign-in with Pocket ID (shared with Kooka and Wallaby)
In Pocket ID add an OIDC client with callback `<PELICAN_URL>/api/oidc/pocketid/callback` and put its id and secret in
`.env` (`PELICAN_OIDC=pocketid`, `PELICAN_OIDC_POCKETID_*`). Kooka and Wallaby take the same kind of settings
(`KOOKA_OIDC_*`, `WALLABY_OIDC_*`): with one Pocket ID behind all three, the family signs in to each with the same
passkey (Face ID / Touch ID). Suggested order: sign up, sign in once with Pocket ID (it links to the same email), invite
your partner, then set `PELICAN_PASSWORD_LOGIN=0` and `PELICAN_SIGNUP=closed`.

### Import by email
Create a mailbox for the archive (e.g. `archivio@yourdomain.it`) and set `PELICAN_INBOX_ADDRESS` and `PELICAN_IMAP_*`.
Pelican reads it every minute over IMAP (nothing to open on the server). Accepted senders: the email of each account
plus the extra addresses each person adds on the Family page; anything else is ignored without answering. With
`PELICAN_IMAP_REQUIRE_AUTH=1` (default) a message is accepted only if your mail server says SPF or DKIM passed
(`Authentication-Results`), so a forged sender cannot drop files into the archive. Answers and summaries need SMTP.

### Backup to the NAS (Borg)
Pelican makes a consistent database copy every night by itself. `scripts/backup-to-nas.sh`, run on the host, sends
that copy, the encrypted files and the keys to an **encrypted Borg repository** on the NAS and records the outcome,
which the Family page shows (with a warning when the last copy failed or is older than 2 days).

One-time setup (on the Pelican host, as root):
```sh
apt install borgbackup
ssh-keygen -t ed25519 -f /root/.ssh/pelican_borg -N ''
# On the NAS, in the borg user's ~/.ssh/authorized_keys (append-only: this server can add backups, never delete them):
#   command="borg serve --append-only --restrict-to-path /volume1/backup/pelican",restrict ssh-ed25519 AAAA… pelican
borg init --encryption=repokey-blake2 ssh://borg@nas.local/./pelican
borg key export ssh://borg@nas.local/./pelican /root/pelican-borg-key.txt   # keep it with the passphrase, off the server
cp scripts/backup.env.example scripts/backup.env && chmod 600 scripts/backup.env   # repository, passphrase, ssh key
scripts/backup-to-nas.sh        # first run
```
Every night, e.g. in root's crontab: `30 3 * * * /srv/pelican/scripts/backup-to-nas.sh`.

Append-only means a compromised server cannot wipe the history; the price is that `prune` only marks old archives:
run `borg compact` from the NAS side (with a non append-only key) now and then to free space.

Restore on a new machine: `borg extract ::pelican-YYYY-MM-DDTHHMM` inside an empty `Pelican_data/`, then
`python manage.py restore backups/manual-….db` with the server stopped, start it, and run `python manage.py verify`.

### Other commands
```sh
docker exec pelican python manage.py backup      # database copy now
docker exec pelican python manage.py verify      # every file present, decrypts, unchanged (SHA-256)
docker exec pelican python manage.py reindex     # rebuild the search index
docker exec pelican python manage.py users       # users and families
```

## Security notes
- Files are encrypted at rest with a key kept apart from the database. This protects a stolen disk or a copied
  `files/` folder; it does not protect against someone who controls the running server (the server must read the
  files to run OCR and show them). The database itself (titles, details and the text read from documents, used
  for search) is not encrypted: put the data on an encrypted disk (LUKS) if the machine could be stolen.
- Original files are always downloaded with their real type; only PDFs, images and plain text open in the browser,
  under a policy that forbids scripts.
- API keys (the iPhone Shortcut) are stored hashed, reach only the archive and the import queue (never account, family or
  security settings) and can be revoked from the Family page.
- Face ID: with Pocket ID the sign-in itself is a passkey. An in-app lock after inactivity is planned with sharing
  (phase 4).

## Development
```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
sudo apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng
cd frontend && npm ci && npm run build && cd ..
cd backend && PELICAN_COOKIE_SECURE=0 ../.venv/bin/python app.py      # http://localhost:3002
.venv/bin/python -m pytest                                              # from the project root
```
`npm run dev` in `frontend/` serves the interface with hot reload and proxies `/api` to port 3002.

## Wombat (one sign-in and one family for all the family apps)
Optional. With `PELICAN_HUB_URL` and `PELICAN_HUB_KEY` set (see `.env.example` and Wombat's README), Pelican signs people in
only through the OIDC provider (the same Pocket ID as Wombat), and takes the family from Wombat: members, roles,
people and who may use Pelican. The family, members and people become read-only here, with a link to Wombat; the copy is
refreshed every 2 minutes and keeps working if Wombat is down. Existing data is adopted, not recreated: run Wombat's
**Import** once (it reads `GET /api/hub/export` with the key). A family someone had made on their own can be merged into the shared one from Wombat's import (`POST /api/hub/merge`: a database backup first, then everything moves; people with the same name become one; a document whose identical file is already there goes to the trash). Without these settings Pelican works on its own as before.

## License
[MIT](LICENSE). No warranty and no liability: see [DISCLAIMER.md](DISCLAIMER.md).

# paTrack – family document archive

> **Disclaimer / Esclusione di responsabilità.** paTrack is provided *as is*, without any warranty: the authors accept **no responsibility or liability** for data loss, security problems, missed reminders, wrong information or any other consequence of using it. Read [DISCLAIMER.md](DISCLAIMER.md) before using it with real data. · Il software è fornito *così com'è*, senza garanzie: gli autori **non hanno alcuna responsabilità**. Leggi [DISCLAIMER.md](DISCLAIMER.md).

Every document of the family in one place: IDs and licences, health (reports, prescriptions, vaccinations), the kids
(paediatrician, nursery, school), home (contracts, mortgage, bills, condominium), car, taxes, work, purchases and
warranties, bank and insurance. Same stack, style and sign-in as **doTrack** and **eaTrack**.

Phase 1 (this version): import, archive, search.

- **Import, never silently lost**
  - **Browser**: drag and drop anywhere in the window (dozens of files at once), file picker, paste.
  - **Scan** with the camera: the sheet's edges are found automatically (corners can be dragged), the page is
    straightened and cleaned up; several pages become one PDF. All in the browser.
  - **iPhone Share menu**: a Shortcut ("Save to paTrack") sends PDFs, photos, Mail/WhatsApp attachments and files with
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

Coming next: automatic proposals (category, person, dates, amount, issuer) that learn from corrections (phase 2);
deadlines sent to doTrack, links to eaTrack, the tax return view (phase 3); per-person sharing (phase 4).

- `backend/` – Flask API + SQLite (waitress, port 3002), OCR worker, IMAP reader
- `frontend/` – Svelte + Vite interface, built into the Docker image

> **Made with AI.** Like doTrack and eaTrack, this project was written by an AI assistant (Anthropic's Claude) and
> checked with automated tests; review it before exposing it to the internet.

## Running with Docker

The code shared with the other family apps is in the `backend/famkit` submodule
([famkit](https://github.com/filippogiuliani/famkit)): clone with
`git clone --recurse-submodules https://github.com/filippogiuliani/patrack.git`, or run `git submodule update --init` in a
clone made without it.

```sh
cp .env.example .env    # set PATRACK_URL, Pocket ID, SMTP, the archive mailbox
./rebuild.sh
```

Data lives in `./paTrack_data/` (mounted on `/app/data`):

| Path | What |
|---|---|
| `patrack.db` | database (documents' details, text read from them, queue, accounts) |
| `files/` | originals and previews, **encrypted** (AES-256-GCM) |
| `.file_key` | the encryption key. **Without it the files cannot be read.** |
| `backups/` | daily consistent copies of the database |
| `offsite.json` | outcome of the last NAS backup (written by the script below) |

Keep a copy of the key outside the server too: `docker exec patrack python manage.py export-key` prints it (base64),
e.g. for a password manager. `import-key` writes it back on a new server.

### Sign-in with Pocket ID (shared with doTrack and eaTrack)
In Pocket ID add an OIDC client with callback `<PATRACK_URL>/api/oidc/pocketid/callback` and put its id and secret in
`.env` (`PATRACK_OIDC=pocketid`, `PATRACK_OIDC_POCKETID_*`). doTrack and eaTrack take the same kind of settings
(`DOTRACK_OIDC_*`, `EATRACK_OIDC_*`): with one Pocket ID behind all three, the family signs in to each with the same
passkey (Face ID / Touch ID). Suggested order: sign up, sign in once with Pocket ID (it links to the same email), invite
your partner, then set `PATRACK_PASSWORD_LOGIN=0` and `PATRACK_SIGNUP=closed`.

### Import by email
Create a mailbox for the archive (e.g. `archivio@yourdomain.it`) and set `PATRACK_INBOX_ADDRESS` and `PATRACK_IMAP_*`.
paTrack reads it every minute over IMAP (nothing to open on the server). Accepted senders: the email of each account
plus the extra addresses each person adds on the Family page; anything else is ignored without answering. With
`PATRACK_IMAP_REQUIRE_AUTH=1` (default) a message is accepted only if your mail server says SPF or DKIM passed
(`Authentication-Results`), so a forged sender cannot drop files into the archive. Answers and summaries need SMTP.

### Backup to the NAS (Borg)
paTrack makes a consistent database copy every night by itself. `scripts/backup-to-nas.sh`, run on the host, sends
that copy, the encrypted files and the keys to an **encrypted Borg repository** on the NAS and records the outcome,
which the Family page shows (with a warning when the last copy failed or is older than 2 days).

One-time setup (on the paTrack host, as root):
```sh
apt install borgbackup
ssh-keygen -t ed25519 -f /root/.ssh/patrack_borg -N ''
# On the NAS, in the borg user's ~/.ssh/authorized_keys (append-only: this server can add backups, never delete them):
#   command="borg serve --append-only --restrict-to-path /volume1/backup/patrack",restrict ssh-ed25519 AAAA… patrack
borg init --encryption=repokey-blake2 ssh://borg@nas.local/./patrack
borg key export ssh://borg@nas.local/./patrack /root/patrack-borg-key.txt   # keep it with the passphrase, off the server
cp scripts/backup.env.example scripts/backup.env && chmod 600 scripts/backup.env   # repository, passphrase, ssh key
scripts/backup-to-nas.sh        # first run
```
Every night, e.g. in root's crontab: `30 3 * * * /srv/patrack/scripts/backup-to-nas.sh`.

Append-only means a compromised server cannot wipe the history; the price is that `prune` only marks old archives:
run `borg compact` from the NAS side (with a non append-only key) now and then to free space.

Restore on a new machine: `borg extract ::patrack-YYYY-MM-DDTHHMM` inside an empty `paTrack_data/`, then
`python manage.py restore backups/manual-….db` with the server stopped, start it, and run `python manage.py verify`.

### Other commands
```sh
docker exec patrack python manage.py backup      # database copy now
docker exec patrack python manage.py verify      # every file present, decrypts, unchanged (SHA-256)
docker exec patrack python manage.py reindex     # rebuild the search index
docker exec patrack python manage.py users       # users and families
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
cd backend && PATRACK_COOKIE_SECURE=0 ../.venv/bin/python app.py      # http://localhost:3002
.venv/bin/python -m pytest                                              # from the project root
```
`npm run dev` in `frontend/` serves the interface with hot reload and proxies `/api` to port 3002.

## weHub (one sign-in and one family for all the family apps)
Optional. With `PATRACK_HUB_URL` and `PATRACK_HUB_KEY` set (see `.env.example` and weHub's README), paTrack signs people in
only through the OIDC provider (the same Pocket ID as weHub), and takes the family from weHub: members, roles,
people and who may use paTrack. The family, members and people become read-only here, with a link to weHub; the copy is
refreshed every 2 minutes and keeps working if weHub is down. Existing data is adopted, not recreated: run weHub's
**Import** once (it reads `GET /api/hub/export` with the key). A family someone had made on their own can be merged into the shared one from weHub's import (`POST /api/hub/merge`: a database backup first, then everything moves; people with the same name become one; a document whose identical file is already there goes to the trash). Without these settings paTrack works on its own as before.

## License
[MIT](LICENSE). No warranty and no liability: see [DISCLAIMER.md](DISCLAIMER.md).

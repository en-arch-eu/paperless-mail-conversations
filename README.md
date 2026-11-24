# paperless-mail-conversations

A Django app for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)
that imports **marked mail conversations** and keeps each mail linked to its
attachments, to the mail it answers and to the mail it forwards.

**Status: early version, in use on one instance.** Written for
Paperless-ngx **3.5.x**. Third-party extensions are not supported by the Paperless team; do
not report problems with this app there.

## What it does

- A mail becomes one document (the original `.eml`, rendered by Paperless'
  mail parser), with custom fields from its headers: from, to, cc, bcc,
  reply-to, sent at, direction, account, `Message-ID`, `In-Reply-To`,
  conversation, key and a web link.
- Attachments become documents linked to the mail with a document link
  field. An attachment already in Paperless (same SHA256) is only linked.
- Replies and forwards are linked to the mail they answer or forward.
- Which attachments become documents is a policy stored in the database
  and can be re-applied to mails already imported (the `.eml` keeps every
  attachment).
- Conversation providers are pluggable. Gmail (label `do-paperless`, thread
  id `X-GM-THRID`) comes first; servers without conversations import single
  marked mails.

Custom field names are in Polish (`Mail: od`, `Mail: załącznik`, ...); see
`src/paperless_mail_conversations/fields.py`.

## Installation (Docker / TrueNAS app)

1. Put the update script in the host directory mounted as `/plugins` and run
   it as root:

   ```
   cd /mnt/tank/apps/paperless/plugins
   curl -fsSLO https://github.com/en-arch-eu/paperless-mail-conversations/releases/latest/download/update-mail-conversations.sh
   chmod 755 update-mail-conversations.sh
   ./update-mail-conversations.sh
   ```

   It downloads the latest wheel, checks it against `SHA256SUMS` and points
   the stable link `paperless_mail_conversations.whl` at it.

2. Add the app to the environment (`:` and `,` separate several apps) and restart:

   ```
   PYTHONPATH=/plugins/paperless_mail_conversations.whl
   PAPERLESS_APPS=paperless_mail_conversations.apps.MailConversationsConfig
   ```

   On start a migration creates the attachment policy table with the default
   rules. Custom fields are created on first use.

3. Check the log for `[mail-conversations] loaded, version 0.1.1`. From now on,
   after every mail fetch, threads labelled `do-paperless` in the Gmail
   accounts configured in Paperless are imported (no mail rule needed).

Run the commands as the `paperless` user (`docker exec -u paperless ...`), or
the worker cannot read the files they queue.

**Rollback:** remove the app from `PAPERLESS_APPS` and `PYTHONPATH`, restart.
Documents and custom fields stay; the policy table stays in the database.

The app uses internal Paperless APIs (`consume_file`, `DocumentMetadataOverrides`,
`reflect_doclinks`, `paperless_mail.mail.get_mailbox`, `django-soft-delete`
signals). Run the tests in `dev/` after every Paperless upgrade.

## Development

```sh
uv run pytest -q                 # core tests, no Paperless needed
uv build                         # wheel for dev/compose.yml
```

`dev/compose.yml` starts a throwaway Paperless 3.5.1 with the app loaded from
the wheel (instructions in the file). Integration check with a sample
conversation (run commands as the `paperless` user, the worker must be able
to read the queued files):

```sh
uv run dev/samples.py            # dev/samples/*.eml and existing.pdf
W=paperless-mail-conversations-dev-webserver-1
curl -u admin:admin -F document=@dev/samples/existing.pdf http://localhost:8011/api/documents/post_document/
docker cp dev/samples $W:/tmp/ && docker cp dev/dump.py $W:/tmp/
docker exec -u paperless $W python3 manage.py mail_conversations_import --address jan@example.org /tmp/samples/02-reply.eml
docker exec -u paperless $W python3 manage.py mail_conversations_import --address jan@example.org /tmp/samples/0[134]*.eml
docker exec -u paperless $W python3 manage.py shell -c "exec(open('/tmp/dump.py').read())"
```

Expected: the reply, the forward and the original linked both ways
(`Mail: odpowiedź`, `Mail: przekazanie`); `existing.pdf` linked, not imported
again; the new PDFs imported with `Mail: z załącznika`; the attached mail
imported as a mail linked by `Mail: przekazanie`; the embedded image and the
signature skipped.

## Commands

- `manage.py mail_conversations_import FILE.eml... [--account NAME] [--address ADDR] [--scope oznaczone|zaległości] [--owner ID]`:
  import mails from files (no conversation provider; the key is the `Message-ID`).
- `manage.py mail_conversations_sync [--account NAME]`: import the marked
  conversations now (it also runs after every Paperless mail fetch).

Gmail test against a real mailbox: `uv run dev/gmail_account.py gmail.env`
creates the account in the dev instance from `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD` (a Google app password); then label a thread
`do-paperless` and run `mail_conversations_sync` as the `paperless` user.

- `manage.py mail_conversations_backfill --account NAME [--query "has:attachment"] [--limit N] [--dry-run] [-v 2]`:
  one-time import of old mails (oldest first) with the backfill policy;
  attachments already in Paperless (same SHA256) are only linked. The
  messages get the `w-paperless` label; their conversations are not watched.
  `--dry-run` only counts (nothing written to Paperless or the mailbox), with
  the skipped attachments by type.
- `manage.py mail_conversations_reconcile [--dry-run] [--pattern '*.jpg'] [--document ID]`:
  re-apply the attachment policy to the mails in Paperless (from their `.eml`):
  import, link or restore from the trash what should be a document; move to
  the trash documents made from attachments (`Mail: z załącznika`) that
  should not be, unless another mail needs them. Documents that were in
  Paperless before are never touched.

The attachment policy is edited in the Django admin (`/admin`, *Attachment
rules*). Each mail records its policy scope in `Mail: zakres` (`oznaczone` or
`zaległości`); a backfilled mail that later shows up in a marked conversation
is switched to `oznaczone` and reconciled. Deleting a document made from an
attachment records its SHA256 in the mail's `Mail: pominięte załączniki`, so
reconcile does not bring it back (delete the line to undo).

ZIP attachments are not documents: their files are (same policy, nested ZIPs
up to 3 levels, names without the UTF-8 flag read as cp852). A ZIP that cannot
be read (encrypted, damaged, over 1000 files or 500 MB) stays one document.

Images without DPI information (common in mail) need `PAPERLESS_OCR_IMAGE_DPI`
set, or Paperless rejects them.

## License

GPL-3.0-or-later, like Paperless-ngx.

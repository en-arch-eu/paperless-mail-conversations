# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-11-24

### Removed

- `PAPERLESS_MAIL_CONVERSATIONS_STORAGE_PATH` and `--storage-path` of
  `mail_conversations_import`: imported documents get no storage path from
  the app (set it later, or with a Paperless workflow).

## [0.1.0] - 2026-11-24

First version, for Paperless-ngx 3.5.1.

### Added

- Package skeleton (CI, release with `SHA256SUMS`, update script, dev compose).
- Core without Paperless: `.eml` parsing, header fields, attachments with
  SHA256, attachment policy, reply and forward detection.
- Paperless integration (tested on 3.5.1): custom fields created on first
  use, attachment policy as a database table edited in the admin (default
  rules from a migration), import of a mail as `.eml` with header fields,
  attachments imported or linked by SHA256, reply and forward links set on
  both sides (also when the reply was imported first), attached mails
  imported as mails (up to 3 levels).
- `manage.py mail_conversations_import` for `.eml` files.
- Conversation providers (entry point group `paperless_mail_conversations.providers`)
  and the Gmail provider: threads with the label `do-paperless` are imported
  whole, messages get the label `w-paperless`; bodies fetched with
  `BODY.PEEK[]` (read state unchanged). Runs after every Paperless mail fetch
  (`task_postrun` of `process_mail_accounts`) and with
  `manage.py mail_conversations_sync`. Storage path for imported documents:
  `PAPERLESS_MAIL_CONVERSATIONS_STORAGE_PATH` (id); owner: the mail account's owner.
- A mail that libmagic reads as `text/plain` (e.g. sent from Gmail: it starts
  with `MIME-Version:`) gets its `From` header moved to the top before
  consumption, as Paperless' own mail import does; otherwise Paperless would
  store it as plain text without the PDF rendering.
- `Mail: zakres` (policy scope of the mail); backfilled mails in a marked
  conversation switch to `oznaczone` and are reconciled.
- ZIP attachments expanded: their files become documents, the ZIP does not.
- `manage.py mail_conversations_backfill` (with `--dry-run` statistics) and
  `manage.py mail_conversations_reconcile`; documents made from attachments
  are restored from the trash when the policy wants them again.
- Deleting a document made from an attachment records its SHA256 in
  `Mail: pominięte załączniki` of its mails.

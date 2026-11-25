# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.5] - 2026-11-25

### Fixed

- An attachment equal to the archive copy of a document (not to its original)
  was queued for import every time, refused by Paperless as a duplicate and
  only then linked. It is now linked at once: a document matches by its
  original or its archive copy, as in Paperless' own duplicate check; also
  for documents in the trash and in `mail_conversations_reconcile`.

## [0.1.4] - 2026-11-25

### Changed

- An attachment Paperless rejected for good is skipped instead of imported
  again after every restart (0.1.3) or reconcile. The reason comes from the
  failed consume task: an unsupported type (`application/encrypted`,
  `application/javascript`), a page size error and the like at once, an
  unknown error after the second failure; errors of a service (Tika,
  Gotenberg, connection, time limit, database, disk) are always retried. The
  SHA256 goes to `Mail: pominięte załączniki` with the file name and the
  reason. The temporary file Paperless consumes is now named after the
  content's SHA256 (`mail-conversations-<16 hex>-…`) to find its tasks;
  attachments that failed before this version are tried once more.

## [0.1.3] - 2026-11-25

### Fixed

- An app restart that empties Redis took the queued work with it: attachment
  imports and the tasks linking an attachment back to its mail. Mails stayed
  without some attachments, and attachments pointed to a mail that did not
  point back. The sync now notices that the cache was emptied (a key that
  never expires is gone) and runs the follow-up of every mail added in the 48
  hours before again; it only adds what is missing (attachments removed by
  hand stay out) and continues in the next sync after 10 minutes.
- Linking a mail whose attachment list holds a document in the trash failed
  (`UNIQUE constraint failed` in Paperless' `reflect_doclinks`: the trashed
  document's field instance is soft-deleted with it). Documents in the trash
  are now left out of the other side of a link; their own links come back
  with them when restored.

## [0.1.2] - 2026-11-24

### Fixed

- Marking many conversations at once (hundreds) blocked the Paperless worker:
  the sync looked up every marked conversation before queueing anything and
  was killed by the task time limit without importing a mail. Now only
  conversations with a marked message not in Paperless are looked up, each is
  queued at once, and a sync stops after 10 minutes (the rest comes with the
  next one). New messages in conversations already imported are found with one
  search of the last 7 days (`newer_than:7d`).
- A queued mail is not queued again for 24 hours (was 1 hour), so a long
  consume queue does not import mails twice.

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

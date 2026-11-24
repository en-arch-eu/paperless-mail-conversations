# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

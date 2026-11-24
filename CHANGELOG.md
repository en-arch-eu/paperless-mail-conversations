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

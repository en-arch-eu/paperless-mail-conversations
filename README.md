# paperless-mail-conversations

A Django app for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)
that imports **marked mail conversations** and keeps each mail linked to its
attachments, to the mail it answers and to the mail it forwards.

**Status: in development, not usable yet.** Written for Paperless-ngx
**3.5.x**. Third-party extensions are not supported by the Paperless team; do
not report problems with this app there.

## What it does (planned)

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

## Development

```sh
uv run pytest -q                 # core tests, no Paperless needed
uv build                         # wheel for dev/compose.yml
```

`dev/compose.yml` starts a throwaway Paperless 3.5.1 with the app loaded from
the wheel (instructions in the file).

## License

GPL-3.0-or-later, like Paperless-ngx.

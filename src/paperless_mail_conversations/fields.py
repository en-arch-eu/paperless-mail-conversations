"""Custom fields of a mail document: names, types and values from the headers."""

from __future__ import annotations

from dataclasses import dataclass

from .mail import Mail, addresses


@dataclass(frozen=True)
class FieldDef:
    name: str
    data_type: str  # Paperless CustomField.FieldDataType value
    select_options: tuple[str, ...] = ()


RECEIVED = "odebrany"
SENT = "wysłany"
SCOPE_MARKED = "oznaczone"  # same labels as policy.Scope
SCOPE_BACKFILL = "zaległości"

FROM = FieldDef("Mail: od", "longtext")
TO = FieldDef("Mail: do", "longtext")
CC = FieldDef("Mail: DW", "longtext")
BCC = FieldDef("Mail: UDW", "longtext")
REPLY_TO = FieldDef("Mail: odpowiedz do", "longtext")
SENT_AT = FieldDef("Mail: wysłano", "string")
DIRECTION = FieldDef("Mail: kierunek", "select", (RECEIVED, SENT))
ACCOUNT = FieldDef("Mail: konto", "string")
MESSAGE_ID = FieldDef("Mail: Message-ID", "longtext")
IN_REPLY_TO = FieldDef("Mail: In-Reply-To", "longtext")
CONVERSATION = FieldDef("Mail: konwersacja", "string")
KEY = FieldDef("Mail: klucz", "string")
LINK = FieldDef("Mail: link", "url")
# which attachment policy applies to the mail; reconcile reads it
SCOPE = FieldDef("Mail: zakres", "select", (SCOPE_MARKED, SCOPE_BACKFILL))

ATTACHMENT = FieldDef("Mail: załącznik", "documentlink")
REPLY = FieldDef("Mail: odpowiedź", "documentlink")
FORWARD = FieldDef("Mail: przekazanie", "documentlink")
FROM_ATTACHMENT = FieldDef("Mail: z załącznika", "boolean")
SKIPPED = FieldDef("Mail: pominięte załączniki", "longtext")

ALL_FIELDS = (
    FROM, TO, CC, BCC, REPLY_TO, SENT_AT, DIRECTION, ACCOUNT, MESSAGE_ID, IN_REPLY_TO,
    CONVERSATION, KEY, LINK, SCOPE, ATTACHMENT, REPLY, FORWARD, FROM_ATTACHMENT, SKIPPED,
)


def header_fields(
    mail: Mail,
    *,
    account_name: str,
    account_address: str,
    message_key: str,
    conversation_key: str | None = None,
    web_link: str | None = None,
) -> dict[FieldDef, str]:
    """Values of the header fields; empty ones are left out."""
    from_addrs = addresses(mail.from_)
    reply_to_differs = set(addresses(mail.reply_to)) - set(from_addrs)
    values = {
        FROM: mail.from_,
        TO: mail.to,
        CC: mail.cc,
        BCC: mail.bcc,
        REPLY_TO: mail.reply_to if reply_to_differs else "",
        SENT_AT: mail.date.isoformat() if mail.date else "",
        DIRECTION: SENT if account_address.lower() in from_addrs else RECEIVED,
        ACCOUNT: account_name,
        MESSAGE_ID: mail.message_id or "",
        IN_REPLY_TO: mail.in_reply_to or "",
        CONVERSATION: conversation_key or "",
        KEY: message_key,
        LINK: web_link or "",
    }
    return {f: v for f, v in values.items() if v}


def parse_skipped(text: str | None) -> set[str]:
    """SHA256 sums listed in ``Mail: pominięte załączniki`` (any whitespace or commas)."""
    return {t.lower() for t in (text or "").replace(",", " ").split() if len(t) == 64}


def add_skipped(text: str | None, sha256: str, note: str | None = None) -> str:
    """The field text with ``sha256`` (and ``note`` after it) added on its own line
    (unchanged if present)."""
    text = (text or "").rstrip()
    if sha256.lower() in parse_skipped(text):
        return text
    line = f"{sha256.lower()} {note}" if note else sha256.lower()
    return f"{text}\n{line}" if text else line

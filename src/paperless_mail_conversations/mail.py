"""Parse a raw mail (``.eml``) into headers, body text and attachments.

Standard library only, so it is tested without Paperless.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

_MSGID = re.compile(r"<[^<>\s]+>")


def normalize_message_id(value: str | None) -> str | None:
    """``<id@host>`` without surrounding text; ``None`` if there is none."""
    if not value:
        return None
    found = _MSGID.search(value)
    if found:
        return found.group(0)
    value = value.strip()
    return f"<{value}>" if value and " " not in value else None


def message_ids(value: str | None) -> list[str]:
    """All ``<id@host>`` in a ``References`` header, in order."""
    return _MSGID.findall(value or "")


def from_header_first(raw: bytes) -> bytes:
    """The same message with its ``From`` header (with continuation lines) moved to the top.

    Paperless picks the parser by libmagic, which reads a message starting with
    ``MIME-Version:`` (e.g. one sent from Gmail) as ``text/plain``; a leading
    ``From:`` makes it ``message/rfc822``. Paperless' own mail import does the
    same (``paperless_mail/mail.py``, ``_process_eml``). Header order carries no
    meaning (RFC 5322, DKIM), the bytes of every header and the body stay as they are.
    """
    end = raw.find(b"\r\n\r\n")
    end = end if end != -1 else raw.find(b"\n\n")
    if end == -1:
        return raw
    head, rest = raw[:end], raw[end:]
    nl = b"\r\n" if head.find(b"\r\n") != -1 else b"\n"
    lines = head.split(nl)
    fields: list[list[bytes]] = []
    for line in lines:
        if line[:1] in (b" ", b"\t") and fields:
            fields[-1].append(line)
        else:
            fields.append([line])
    index = next((i for i, f in enumerate(fields) if f[0].lower().startswith(b"from:")), None)
    if not index:  # absent, or already first
        return raw
    fields.insert(0, fields.pop(index))
    return nl.join(line for f in fields for line in f) + rest


def addresses(value: str | None) -> list[str]:
    """Bare lower-case addresses from an address header."""
    return [a.lower() for _, a in getaddresses([value or ""]) if a]


@dataclass(frozen=True)
class Attachment:
    filename: str | None
    mime_type: str
    content: bytes = field(repr=False)
    embedded: bool  # image shown inside the body (Content-ID / inline), not a file
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", hashlib.sha256(self.content).hexdigest())

    @property
    def is_message(self) -> bool:
        """An attached mail (``message/rfc822`` or ``*.eml``)."""
        return self.mime_type == "message/rfc822" or (self.filename or "").lower().endswith(".eml")


@dataclass(frozen=True)
class Mail:
    subject: str
    from_: str
    to: str
    cc: str
    bcc: str
    reply_to: str
    date: datetime | None
    message_id: str | None
    in_reply_to: str | None
    references: list[str]
    body_text: str
    attachments: list[Attachment]


def _header(msg: EmailMessage, name: str) -> str:
    value = msg.get(name)
    return " ".join(str(value).split()) if value is not None else ""


def _date(msg: EmailMessage) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None


def _walk(part: EmailMessage, body: list[str], found: list[Attachment]) -> None:
    """Collect body text and attachments; an attached mail is one attachment,
    its own parts are not entered."""
    mime = part.get_content_type()
    disposition = part.get_content_disposition()  # "attachment", "inline" or None
    filename = part.get_filename()

    if mime == "message/rfc822":
        found.append(Attachment(filename, mime, part.get_content().as_bytes(), embedded=False))
        return

    if part.is_multipart():
        for sub in part.iter_parts():
            _walk(sub, body, found)
        return

    if mime in ("text/plain", "text/html") and disposition != "attachment" and not filename:
        if mime == "text/plain":
            body.append(part.get_content())
        else:
            body.append(re.sub(r"<[^>]+>", " ", part.get_content()))
        return

    content = part.get_payload(decode=True) or b""
    embedded = mime.startswith("image/") and disposition != "attachment" and (
        disposition == "inline" or part.get("Content-ID") is not None
    )
    found.append(Attachment(filename, mime, content, embedded=embedded))


def parse_mail(raw: bytes) -> Mail:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[assignment]
    body: list[str] = []
    found: list[Attachment] = []
    if msg.is_multipart():
        for sub in msg.iter_parts():
            _walk(sub, body, found)
    else:
        _walk(msg, body, found)
    return Mail(
        subject=_header(msg, "Subject"),
        from_=_header(msg, "From"),
        to=_header(msg, "To"),
        cc=_header(msg, "Cc"),
        bcc=_header(msg, "Bcc"),
        reply_to=_header(msg, "Reply-To"),
        date=_date(msg),
        message_id=normalize_message_id(_header(msg, "Message-ID")),
        in_reply_to=normalize_message_id(_header(msg, "In-Reply-To")),
        references=message_ids(_header(msg, "References")),
        body_text="\n".join(body),
        attachments=found,
    )


__all__ = ["Attachment", "Mail", "addresses", "message_ids", "normalize_message_id", "parse_mail"]

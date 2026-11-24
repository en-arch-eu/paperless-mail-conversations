"""Which other mail a mail answers or forwards (by Message-ID)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .mail import Mail

# "Fwd:", "Fw:", "PD:" (Polish Outlook), optionally after a "[tag]".
_FORWARD_SUBJECT = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:fwd?|pd)\s*:", re.IGNORECASE)
# Gmail's forward separator. The Polish variant is an assumption, not seen yet.
_FORWARD_BODY = re.compile(
    r"^-{5,}\s*(?:Forwarded message|Wiadomość przekazana|Przekazana wiadomość)\s*-{5,}",
    re.IGNORECASE | re.MULTILINE,
)

MAX_DEPTH = 3  # attached mails inside attached mails


class Kind(Enum):
    REPLY = "reply"
    FORWARD = "forward"


@dataclass(frozen=True)
class Relation:
    kind: Kind
    message_id: str  # of the mail answered or forwarded


def parent_message_id(mail: Mail) -> str | None:
    """``In-Reply-To``, or the last ``References`` entry when it is missing."""
    if mail.in_reply_to:
        return mail.in_reply_to
    return mail.references[-1] if mail.references else None


def is_forward(mail: Mail) -> bool:
    return bool(_FORWARD_SUBJECT.match(mail.subject) or _FORWARD_BODY.search(mail.body_text))


def relation(mail: Mail) -> Relation | None:
    """Reply or forward of the parent mail; ``None`` for a mail that starts a conversation.

    Gmail sets ``In-Reply-To``/``References`` on a forward too, so only the
    subject prefix or the separator line in the body tells them apart.
    """
    parent = parent_message_id(mail)
    if parent is None or parent == mail.message_id:
        return None
    return Relation(Kind.FORWARD if is_forward(mail) else Kind.REPLY, parent)

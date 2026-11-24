"""Conversation providers: which messages are marked, how they group into conversations.

A provider works on a logged-in ``imap_tools.MailBox``. Built-in: Gmail. More
providers can be added by other packages through the entry point group
``paperless_mail_conversations.providers`` (a ``Provider`` subclass).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from importlib.metadata import entry_points

logger = logging.getLogger("paperless.mail_conversations")

MARK_LABEL = "do-paperless"
IMPORTED_LABEL = "w-paperless"


@dataclass(frozen=True)
class MessageRef:
    """A message in the mailbox: IMAP UID in the provider's folder plus stable ids."""

    uid: str
    message_key: str
    conversation_key: str | None
    web_link: str | None


class Provider:
    name = ""

    def supports(self, mailbox) -> bool:
        raise NotImplementedError

    def open(self, mailbox) -> None:
        """Select the folder the provider works in."""

    def marked(self, mailbox) -> list[MessageRef]:
        """Messages marked by the owner."""
        raise NotImplementedError

    def conversation(self, mailbox, ref: MessageRef) -> list[MessageRef]:
        """All messages of the conversation of ``ref`` (``[ref]`` without conversations)."""
        return [ref]

    def search(self, mailbox, query: str) -> list[MessageRef]:
        """Messages matching a provider-specific query (used by the backfill)."""
        raise NotImplementedError(f"{self.name}: no search")

    def fetch(self, mailbox, refs: list[MessageRef]) -> dict[str, bytes]:
        """Raw messages by UID, without setting \\Seen."""
        out: dict[str, bytes] = {}
        for ref in refs:
            typ, data = mailbox.client.uid("FETCH", ref.uid, "(BODY.PEEK[])")
            if typ != "OK":
                raise RuntimeError(f"FETCH {ref.uid}: {typ} {data!r}")
            out.update(parse_bodies(data))
        return out

    def mark_imported(self, mailbox, ref: MessageRef) -> None:
        raise NotImplementedError


# --- IMAP response parsing (pure, unit tested) ---------------------------------

_ATTR = re.compile(rb"\b(UID|X-GM-THRID|X-GM-MSGID)\s+(\d+)")


def _head(item) -> bytes | None:
    if isinstance(item, tuple):
        return item[0]
    if isinstance(item, bytes) and item != b")":
        return item
    return None


def parse_fetch_attrs(data: list) -> list[dict[str, str]]:
    """``UID``/``X-GM-THRID``/``X-GM-MSGID`` from each item of a FETCH response."""
    out = []
    for item in data:
        head = _head(item)
        if not head:
            continue
        attrs = {k.decode(): v.decode() for k, v in _ATTR.findall(head)}
        if "UID" in attrs:
            out.append(attrs)
    return out


def parse_bodies(data: list) -> dict[str, bytes]:
    """``UID -> raw message`` from a ``FETCH (BODY.PEEK[])`` response."""
    out = {}
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            found = re.search(rb"\bUID\s+(\d+)", item[0])
            if found:
                out[found.group(1).decode()] = item[1]
    return out


def parse_search(data: list) -> list[str]:
    return [u.decode() for chunk in data if chunk for u in chunk.split()]


# --- Gmail -------------------------------------------------------------------


class GmailProvider(Provider):
    """Marked = label ``do-paperless`` on any message of the thread; works in All Mail."""

    name = "gmail"

    def supports(self, mailbox) -> bool:
        return "X-GM-EXT-1" in mailbox.client.capabilities

    def open(self, mailbox) -> None:
        # "[Gmail]/All Mail" has a localised name; find it by its special-use flag
        for folder in mailbox.folder.list():
            if "\\All" in folder.flags:
                mailbox.folder.set(folder.name)
                return
        raise RuntimeError("Gmail: no folder with the \\All flag")

    def _refs(self, mailbox, uids: list[str]) -> list[MessageRef]:
        if not uids:
            return []
        typ, data = mailbox.client.uid("FETCH", ",".join(uids), "(X-GM-THRID X-GM-MSGID)")
        if typ != "OK":
            raise RuntimeError(f"Gmail FETCH ids: {typ} {data!r}")
        return [
            MessageRef(
                uid=a["UID"],
                message_key=f"gmail:{a['X-GM-MSGID']}",
                conversation_key=f"gmail:{a['X-GM-THRID']}",
                web_link=gmail_web_link(a["X-GM-THRID"]),
            )
            for a in parse_fetch_attrs(data)
        ]

    def _search(self, mailbox, *criteria: str) -> list[str]:
        typ, data = mailbox.client.uid("SEARCH", *criteria)
        if typ != "OK":
            raise RuntimeError(f"Gmail SEARCH {criteria}: {typ} {data!r}")
        return parse_search(data)

    def marked(self, mailbox) -> list[MessageRef]:
        return self.search(mailbox, f"label:{MARK_LABEL}")

    def search(self, mailbox, query: str) -> list[MessageRef]:
        """Messages matching a Gmail search query, oldest first."""
        uids = self._search(mailbox, "X-GM-RAW", '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"')
        refs: list[MessageRef] = []
        for i in range(0, len(uids), 500):  # keep the FETCH command short
            refs += self._refs(mailbox, uids[i : i + 500])
        return refs

    def conversation(self, mailbox, ref: MessageRef) -> list[MessageRef]:
        thrid = ref.conversation_key.removeprefix("gmail:")
        return self._refs(mailbox, self._search(mailbox, "X-GM-THRID", thrid))

    def mark_imported(self, mailbox, ref: MessageRef) -> None:
        typ, data = mailbox.client.uid("STORE", ref.uid, "+X-GM-LABELS", IMPORTED_LABEL)
        if typ != "OK":
            raise RuntimeError(f"Gmail STORE label: {typ} {data!r}")


def gmail_web_link(thrid: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{int(thrid):x}"


# --- registry ----------------------------------------------------------------


def providers() -> list[Provider]:
    found: list[Provider] = []
    for ep in entry_points(group="paperless_mail_conversations.providers"):
        try:
            found.append(ep.load()())
        except Exception:
            logger.exception("[mail-conversations] cannot load provider %s", ep.name)
    found.append(GmailProvider())
    return found


def provider_for(mailbox) -> Provider | None:
    return next((p for p in providers() if p.supports(mailbox)), None)

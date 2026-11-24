from types import SimpleNamespace

import pytest

from paperless_mail_conversations.providers import (
    GmailProvider,
    MessageRef,
    gmail_web_link,
    parse_bodies,
    parse_fetch_attrs,
    parse_search,
)

# imaplib shapes: plain bytes for attribute-only items, (head, literal) tuples plus b")" for bodies
IDS = [
    b"1 (X-GM-THRID 1789000000000000001 X-GM-MSGID 1789000000000000001 UID 11)",
    b"2 (UID 12 X-GM-MSGID 1789000000000000002 X-GM-THRID 1789000000000000001)",
]
BODIES = [(b"1 (UID 11 BODY[] {5}", b"raw-1"), b")", (b"2 (UID 12 BODY[] {5}", b"raw-2"), b")"]


def test_parse_fetch_attrs_any_order():
    assert parse_fetch_attrs(IDS) == [
        {"X-GM-THRID": "1789000000000000001", "X-GM-MSGID": "1789000000000000001", "UID": "11"},
        {"UID": "12", "X-GM-MSGID": "1789000000000000002", "X-GM-THRID": "1789000000000000001"},
    ]


def test_parse_bodies_and_search():
    assert parse_bodies(BODIES) == {"11": b"raw-1", "12": b"raw-2"}
    assert parse_search([b"11 12 13"]) == ["11", "12", "13"]
    assert parse_search([b""]) == [] and parse_search([None]) == []


def test_web_link_is_hex_thread_id():
    assert gmail_web_link("1789000000000000001") == "https://mail.google.com/mail/u/0/#all/18d3ce057f2c8001"  # hex(1789000000000000001)


class FakeClient:
    capabilities = ("IMAP4REV1", "X-GM-EXT-1")

    def __init__(self):
        self.calls = []

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH" and args[0] == "X-GM-RAW":
            return "OK", [b"12"]
        if command == "SEARCH" and args[0] == "X-GM-THRID":
            return "OK", [b"11 12"]
        if command == "FETCH" and "X-GM-THRID" in args[1]:
            wanted = args[0].split(",")
            return "OK", [i for i in IDS if parse_fetch_attrs([i])[0]["UID"] in wanted]
        if command == "FETCH":
            return "OK", [b for b in BODIES if isinstance(b, tuple) and f"UID {args[0]} ".encode() in b[0]] + [b")"]
        if command == "STORE":
            return "OK", [b""]
        return "NO", [b"unexpected"]


@pytest.fixture
def mailbox():
    folders = [SimpleNamespace(name="INBOX", flags=()), SimpleNamespace(name="[Gmail]/Wszystkie", flags=("\\HasNoChildren", "\\All"))]
    box = SimpleNamespace(client=FakeClient(), selected=None)
    box.folder = SimpleNamespace(list=lambda: folders, set=lambda name: setattr(box, "selected", name))
    return box


def test_gmail_flow(mailbox):
    p = GmailProvider()
    assert p.supports(mailbox)
    p.open(mailbox)
    assert mailbox.selected == "[Gmail]/Wszystkie"

    [marked] = p.marked(mailbox)
    assert marked == MessageRef("12", "gmail:1789000000000000002", "gmail:1789000000000000001", gmail_web_link("1789000000000000001"))
    assert ("SEARCH", "X-GM-RAW", '"label:do-paperless"') in mailbox.client.calls

    thread = p.conversation(mailbox, marked)
    assert [r.uid for r in thread] == ["11", "12"]
    assert ("SEARCH", "X-GM-THRID", "1789000000000000001") in mailbox.client.calls

    assert p.fetch(mailbox, thread) == {"11": b"raw-1", "12": b"raw-2"}
    assert all(c[2] == "(BODY.PEEK[])" for c in mailbox.client.calls if c[0] == "FETCH" and "BODY" in c[2])

    p.mark_imported(mailbox, marked)
    assert mailbox.client.calls[-1] == ("STORE", "12", "+X-GM-LABELS", "w-paperless")

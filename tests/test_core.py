import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paperless_mail_conversations import fields as F
from paperless_mail_conversations.links import Kind, Relation, relation
from paperless_mail_conversations.mail import Attachment, normalize_message_id, parse_mail
from paperless_mail_conversations.policy import Decision, Rule, Scope, decide

DATA = Path(__file__).parent / "data"
PDF_FAKTURA = hashlib.sha256(b"%PDF-1.4 faktura").hexdigest()
PDF_UMOWA = hashlib.sha256(b"%PDF-1.4 umowa").hexdigest()


def load(name: str):
    return parse_mail((DATA / name).read_bytes())


def by_name(mail):
    return {a.filename: a for a in mail.attachments}


# --- parsing --------------------------------------------------------------


def test_headers_decoded():
    m = load("01-attachments.eml")
    assert m.subject == "Faktura za październik"
    assert m.from_ == "Sklep Łódź <sklep@example.com>"
    assert m.to == "Jan Testowy <jan@example.org>"
    assert m.cc == "ksiegowosc@example.org"
    assert m.message_id == "<orig-1@example.com>"
    assert m.in_reply_to is None and m.references == []
    assert m.date == datetime(2026, 11, 3, 14, 5, 9, tzinfo=timezone(timedelta(hours=1)))
    assert "W załączniku faktura." in m.body_text


def test_attachments_with_embedded_image_and_signature():
    atts = by_name(load("01-attachments.eml"))
    assert set(atts) == {"logo.gif", "faktura październik.pdf", "smime.p7s"}
    assert atts["logo.gif"].embedded
    pdf = atts["faktura październik.pdf"]
    assert not pdf.embedded and pdf.mime_type == "application/pdf"
    assert pdf.sha256 == PDF_FAKTURA


def test_rfc2047_filename_in_quotes():
    atts = by_name(load("03-forward-inline.eml"))
    assert atts["faktura październik.pdf"].sha256 == PDF_FAKTURA


def test_attached_mail_is_one_attachment_and_parses_again():
    m = load("04-forward-attached.eml")
    assert [a.mime_type for a in m.attachments] == ["message/rfc822", "application/pdf"]
    inner_att, scan = m.attachments
    assert inner_att.is_message and inner_att.filename is None
    assert not scan.embedded  # a PDF with "inline" disposition (Apple Mail) is a file
    inner = parse_mail(inner_att.content)
    assert inner.message_id == "<inner-0@example.com>"
    assert [a.sha256 for a in inner.attachments] == [PDF_UMOWA]
    assert "Umowa do podpisu." not in m.body_text  # the attached mail's body is not ours


def test_bad_date_and_bare_addresses():
    m = load("05-references-only.eml")
    assert m.date is None
    assert m.references == ["<orig-1@example.com>", "<reply-2@example.org>"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<a@b>", "<a@b>"),
        ("  <a@b> (comment)", "<a@b>"),
        ("a@b", "<a@b>"),
        ("", None),
        (None, None),
        ("two words", None),
    ],
)
def test_normalize_message_id(raw, expected):
    assert normalize_message_id(raw) == expected


# --- header fields --------------------------------------------------------


def test_header_fields_received():
    m = load("01-attachments.eml")
    values = F.header_fields(
        m,
        account_name="GMail",
        account_address="jan@example.org",
        message_key="gmail:1",
        conversation_key="gmail:100",
        web_link="https://mail.google.com/mail/u/0/#all/64",
    )
    assert values == {
        F.FROM: "Sklep Łódź <sklep@example.com>",
        F.TO: "Jan Testowy <jan@example.org>",
        F.CC: "ksiegowosc@example.org",
        F.REPLY_TO: "faktury@example.com",
        F.SENT_AT: "2026-11-03T14:05:09+01:00",
        F.DIRECTION: F.RECEIVED,
        F.ACCOUNT: "GMail",
        F.MESSAGE_ID: "<orig-1@example.com>",
        F.CONVERSATION: "gmail:100",
        F.KEY: "gmail:1",
        F.LINK: "https://mail.google.com/mail/u/0/#all/64",
    }


def test_header_fields_sent_without_conversation():
    m = load("02-reply-sent.eml")
    values = F.header_fields(m, account_name="GMail", account_address="jan@example.org", message_key="<reply-2@example.org>")
    assert values[F.DIRECTION] == F.SENT  # address compared case-insensitively
    assert values[F.BCC] == "archiwum@example.org"
    assert values[F.IN_REPLY_TO] == "<orig-1@example.com>"
    assert F.CONVERSATION not in values and F.LINK not in values and F.REPLY_TO not in values


def test_reply_to_same_as_from_is_left_out():
    m = parse_mail(b"From: A <a@x>\r\nReply-To: a@X\r\nSubject: s\r\n\r\nbody\r\n")
    values = F.header_fields(m, account_name="k", account_address="me@x", message_key="k1")
    assert F.REPLY_TO not in values


def test_field_definitions():
    names = [f.name for f in F.ALL_FIELDS]
    assert len(names) == len(set(names)) == 18
    assert F.DIRECTION.select_options == (F.RECEIVED, F.SENT)
    # "string" holds at most 128 characters in Paperless
    assert {f.name for f in F.ALL_FIELDS if f.data_type == "string"} == {
        "Mail: wysłano", "Mail: konto", "Mail: konwersacja", "Mail: klucz",
    }


def test_skipped_list():
    a, b = "a" * 64, "B" * 64
    assert F.parse_skipped(None) == set()
    text = F.add_skipped(None, a)
    assert text == a
    text = F.add_skipped(text, b)
    assert text == f"{a}\n{'b' * 64}"
    assert F.add_skipped(text, a) == text
    assert F.parse_skipped(f"{a}, not-a-sum\n\n{b}") == {a, "b" * 64}


# --- links ----------------------------------------------------------------


def test_first_mail_has_no_relation():
    assert relation(load("01-attachments.eml")) is None
    assert relation(load("04-forward-attached.eml")) is None


def test_reply():
    assert relation(load("02-reply-sent.eml")) == Relation(Kind.REPLY, "<orig-1@example.com>")


def test_forward_in_body_by_subject_and_separator():
    assert relation(load("03-forward-inline.eml")) == Relation(Kind.FORWARD, "<orig-1@example.com>")


def test_forward_by_separator_only():
    raw = (DATA / "03-forward-inline.eml").read_bytes().replace(b"Subject: Fwd: ", b"Subject: ")
    assert relation(parse_mail(raw)).kind is Kind.FORWARD


def test_references_used_without_in_reply_to_and_pd_prefix_after_tag():
    assert relation(load("05-references-only.eml")) == Relation(Kind.FORWARD, "<reply-2@example.org>")


@pytest.mark.parametrize(
    ("subject", "kind"),
    [("Fwd: x", Kind.FORWARD), ("FW: x", Kind.FORWARD), ("PD: x", Kind.FORWARD),
     ("Re: Fwd: x", Kind.REPLY), ("Re: x", Kind.REPLY), ("Fwdx: y", Kind.REPLY)],
)
def test_subject_prefixes(subject, kind):
    raw = f"Subject: {subject}\r\nIn-Reply-To: <p@x>\r\n\r\nbody\r\n".encode()
    assert relation(parse_mail(raw)).kind is kind


# --- policy ---------------------------------------------------------------


def att(filename, mime="application/octet-stream", embedded=False, content=b"x"):
    return Attachment(filename, mime, content, embedded=embedded)


@pytest.mark.parametrize(
    ("attachment", "marked", "backfill"),
    [
        (att("faktura.PDF", "application/pdf"), Decision.DOCUMENT, Decision.DOCUMENT),
        (att("logo.gif", "image/gif", embedded=True), Decision.SKIP, Decision.SKIP),
        (att("zdjecie.jpg", "image/jpeg"), Decision.DOCUMENT, Decision.SKIP),
        (att("smime.p7s"), Decision.SKIP, Decision.SKIP),
        (att("zaproszenie.ics", "text/calendar"), Decision.SKIP, Decision.SKIP),
        (att("dane.zip", "application/zip"), Decision.DOCUMENT, Decision.DOCUMENT),
        (att(None, "message/rfc822"), Decision.DOCUMENT, Decision.DOCUMENT),
        (att("trasa.gpx"), Decision.DOCUMENT, Decision.SKIP),
    ],
)
def test_default_policy(attachment, marked, backfill):
    assert decide(attachment, Scope.MARKED) is marked
    assert decide(attachment, Scope.BACKFILL) is backfill


def test_rules_in_order_mime_and_scope_all():
    rules = [
        Rule("image/*", Decision.SKIP, Scope.ALL),
        Rule("*", Decision.DOCUMENT, Scope.MARKED),
    ]
    assert decide(att("a.jpg", "image/jpeg"), Scope.MARKED, rules) is Decision.SKIP
    assert decide(att("a.txt", "text/plain"), Scope.MARKED, rules) is Decision.DOCUMENT
    assert decide(att("a.txt", "text/plain"), Scope.BACKFILL, rules) is Decision.SKIP


def test_skipped_by_owner_wins():
    pdf = att("faktura.pdf", "application/pdf")
    assert decide(pdf, Scope.MARKED, skipped={pdf.sha256}) is Decision.SKIP

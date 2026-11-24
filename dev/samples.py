"""Write a test conversation as .eml files into dev/samples/ (local test data only).

    uv run dev/samples.py

01 original with a new PDF, an embedded image and a signature (skipped);
02 reply with a PDF that is already in Paperless (existing.pdf, upload it first);
03 forward in the body ("Fwd:");
04 mail with an attached mail that has its own PDF.
Import 02 before 01 to check that a reply imported first gets linked.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent / "samples"
TZ = timezone(timedelta(hours=1))


def pdf(text: str) -> bytes:
    """A minimal valid one-page PDF with ``text``."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def mail(subject, sender, to, when, msgid, body, in_reply_to=None) -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = sender
    m["To"] = to
    m["Date"] = format_datetime(when)
    m["Message-ID"] = msgid
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    m.set_content(body)
    return m


def main() -> None:
    OUT.mkdir(exist_ok=True)
    me, shop = "Jan Testowy <jan@example.org>", "Sklep Łódź <sklep@example.com>"
    t0 = datetime(2026, 11, 3, 14, 5, tzinfo=TZ)
    existing = pdf("Regulamin sklepu")
    (OUT / "existing.pdf").write_bytes(existing)

    m1 = mail("Faktura za październik", shop, me, t0, "<orig-1@example.com>", "W załączniku faktura.")
    m1.add_alternative('<p>W załączniku faktura.<img src="cid:logo@x"></p>', subtype="html")
    m1.get_payload()[1].add_related(b"GIF89a-logo", "image", "gif", cid="<logo@x>", filename="logo.gif", disposition="inline")
    m1.add_attachment(pdf("Faktura 10/2026"), "application", "pdf", filename="faktura październik.pdf")
    m1.add_attachment(b"sig", "application", "pkcs7-signature", filename="smime.p7s")

    m2 = mail("Re: Faktura za październik", me, shop, t0 + timedelta(days=1), "<reply-2@example.org>",
              "Dziękuję. Odsyłam regulamin.", in_reply_to="<orig-1@example.com>")
    m2.add_attachment(existing, "application", "pdf", filename="regulamin.pdf")

    m3 = mail("Fwd: Faktura za październik", me, "Anna <anna@example.net>", t0 + timedelta(days=2),
              "<fwd-3@example.org>", "Do wiadomości.\n\n---------- Forwarded message ---------\nFrom: Sklep",
              in_reply_to="<orig-1@example.com>")

    inner = mail("Umowa", "Biuro <biuro@example.com>", "anna@example.net", t0 - timedelta(days=1),
                 "<inner-0@example.com>", "Umowa do podpisu.")
    inner.add_attachment(pdf("Umowa najmu"), "application", "pdf", filename="umowa.pdf")
    m4 = mail("umowa w załączniku", "Anna <anna@example.net>", me, t0 + timedelta(days=3), "<att-4@example.net>",
              "Przesyłam maila z umową.")
    m4.add_attachment(inner)

    for name, m in [("01-original", m1), ("02-reply", m2), ("03-forward", m3), ("04-attached-mail", m4)]:
        (OUT / f"{name}.eml").write_bytes(m.as_bytes())
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()

import io
import zipfile

from paperless_mail_conversations.mail import Attachment
from paperless_mail_conversations.plan import expand_zip, plan_attachments
from paperless_mail_conversations.policy import DEFAULT_RULES, Decision, Rule, Scope


class Cp852Info(zipfile.ZipInfo):
    """What old Windows tools write: the name in cp852, no UTF-8 flag."""

    def _encodeFilenameFlags(self):
        return self.filename.encode("cp852"), self.flag_bits & ~0x800


def make_zip(files: dict[str, bytes], utf8_names: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr((zipfile.ZipInfo if utf8_names else Cp852Info)(name), content)
    return buf.getvalue()


def att(name, content=b"x", mime="application/octet-stream", embedded=False):
    return Attachment(name, mime, content, embedded=embedded)


def test_zip_expanded_with_policy_and_junk_skipped():
    z = att("docs.zip", make_zip({
        "a/faktura.pdf": b"pdf", "zdjecie.jpg": b"jpg", "__MACOSX/._faktura.pdf": b"junk", "dir/": b"",
    }), "application/zip")
    marked = plan_attachments([z], Scope.MARKED, DEFAULT_RULES)
    assert sorted(a.filename for a in marked.files) == ["faktura.pdf", "zdjecie.jpg"]
    assert {a.mime_type for a in marked.files} == {"application/pdf", "image/jpeg"}
    backfill = plan_attachments([z], Scope.BACKFILL, DEFAULT_RULES)
    assert [a.filename for a in backfill.files] == ["faktura.pdf"]


def test_nested_zip_and_duplicates_once():
    inner = make_zip({"umowa.pdf": b"umowa"})
    outer = att("outer.zip", make_zip({"inner.zip": inner, "umowa-kopia.pdf": b"umowa"}))
    plan = plan_attachments([outer, att("umowa.pdf", b"umowa")], Scope.MARKED, DEFAULT_RULES)
    assert [a.filename for a in plan.files] == ["umowa.pdf"]  # same content three times


def test_unreadable_zip_stays_a_file():
    broken = att("broken.zip", b"PK\x03\x04 not really")
    assert expand_zip(broken) is None
    assert plan_attachments([broken], Scope.MARKED, DEFAULT_RULES).files == [broken]


def test_polish_names_without_utf8_flag():
    [entry] = expand_zip(att("x.zip", make_zip({"Zażółć gęślą.pdf": b"1"}, utf8_names=False)))
    assert entry.filename == "Zażółć gęślą.pdf"
    [entry] = expand_zip(att("x.zip", make_zip({"Zażółć.pdf": b"1"})))
    assert entry.filename == "Zażółć.pdf"


def test_attached_mails_and_skipped():
    mail = Attachment(None, "message/rfc822", b"From: a@x\r\n\r\nbody", embedded=False)
    pdf = att("a.pdf", b"pdf")
    plan = plan_attachments([mail, pdf, att("logo.gif", mime="image/gif", embedded=True)],
                            Scope.MARKED, DEFAULT_RULES, skipped={pdf.sha256})
    assert plan.mails == [mail] and plan.files == []


def test_zip_skipped_by_policy_is_not_expanded():
    z = att("a.zip", make_zip({"a.pdf": b"1"}))
    rules = [Rule("*.zip", Decision.SKIP, Scope.ALL), *DEFAULT_RULES]
    assert plan_attachments([z], Scope.MARKED, rules).files == []

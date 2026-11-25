import pytest

from paperless_mail_conversations.fields import add_skipped, parse_skipped
from paperless_mail_conversations.rejections import reason, rejected_for_good

# messages as Paperless 3.5.1 stored them in production
ENCRYPTED = "statement.xlsx: Unsupported mime type application/encrypted"
PAGE_SIZE = "linia.png: Error occurred while consuming document linia.png: ValueError: Page size must be between 3 and 14400 PDF units"
SUBPROCESS = "scan.pdf: Error occurred while consuming document scan.pdf: SubprocessOutputError: . See logs for more information."
TIKA = "a.docx: Error occurred while consuming document a.docx: Could not parse content with tika server at http://tika:9998: ConnectError"


def test_reason_drops_the_file_name():
    assert reason(PAGE_SIZE, "linia.png") == "ValueError: Page size must be between 3 and 14400 PDF units"
    assert reason(ENCRYPTED, "statement.xlsx") == "Unsupported mime type application/encrypted"


@pytest.mark.parametrize("message", [ENCRYPTED, PAGE_SIZE])
def test_file_errors_are_permanent_at_once(message):
    assert rejected_for_good(message, failures=1)


def test_service_errors_are_always_retried():
    assert not rejected_for_good(TIKA, failures=5)


def test_unknown_errors_count_after_repeats():
    assert not rejected_for_good(SUBPROCESS, failures=1)
    assert rejected_for_good(SUBPROCESS, failures=2)


def test_a_file_name_does_not_decide():
    message = "timeout-report.pdf: Unsupported mime type application/encrypted"
    assert rejected_for_good(message, failures=1, filename="timeout-report.pdf")


def test_skipped_with_a_note():
    sha = "a" * 64
    text = add_skipped("b" * 64, sha, "statement.xlsx: odrzucony przez Paperless: Unsupported mime type")
    assert text.splitlines()[1] == f"{sha} statement.xlsx: odrzucony przez Paperless: Unsupported mime type"
    assert parse_skipped(text) == {"a" * 64, "b" * 64}
    assert add_skipped(text, sha, "again") == text

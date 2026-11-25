"""Whether Paperless rejected an attachment for good (no Paperless or Django imports).

An attachment Paperless cannot consume (an encrypted spreadsheet, an image too
small for a PDF page) fails again on every retry, so it should be skipped; one
that failed because a service was down (Tika, the database, a time limit) should
be retried. The reason is read from the consumer's error message.
"""

from __future__ import annotations

import re

#: The service failed, not the file: always retry.
TRANSIENT = re.compile(
    r"tika|gotenberg|connect|timed? ?out|temporar|unavailable|no space left|database|locked|"
    r"memory|worker|time ?limit|no such file|not found",
    re.IGNORECASE,
)

#: The file itself cannot be consumed: skip at once.
PERMANENT = re.compile(
    r"unsupported mime type|not supported|page size must be|encrypted|password|unidentifiedimage|"
    r"decompressionbomb|pdfreaderror|pdfparse|invalid pdf|corrupt",
    re.IGNORECASE,
)

#: Failures with the same file after which an unknown error counts as permanent.
REPEATS = 2


def reason(message: str, filename: str | None = None) -> str:
    """The error message without the file name (which may contain any word)."""
    text = message or ""
    for name in {filename, *(re.findall(r"consuming document (.+?): ", text))} - {None, ""}:
        text = text.replace(name, "")
    text = re.sub(r"^[\s:]+", "", text)
    text = re.sub(r"Error occurred while consuming document\s*:\s*", "", text)
    return " ".join(text.split())


def rejected_for_good(message: str, failures: int, filename: str | None = None) -> bool:
    text = reason(message, filename)
    if TRANSIENT.search(text):
        return False
    return bool(PERMANENT.search(text)) or failures >= REPEATS

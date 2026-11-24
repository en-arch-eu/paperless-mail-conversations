"""Attachment policy: which attachments become documents.

A rule matches an attachment by patterns (comma separated, case-insensitive):

- a file name glob (``*.pdf``);
- a MIME glob, recognised by ``/`` (``image/*``);
- the word ``inline``: an image embedded in the body.

The first rule of the scope that matches decides. Rules with scope ``all``
apply to every scope. No matching rule: skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatchcase

from .mail import Attachment


class Decision(Enum):
    DOCUMENT = "dokument"
    SKIP = "pomiń"


class Scope(Enum):
    MARKED = "oznaczone"
    BACKFILL = "zaległości"
    ALL = "wszystkie"


@dataclass(frozen=True)
class Rule:
    patterns: str
    decision: Decision
    scope: Scope

    def matches(self, att: Attachment) -> bool:
        name = effective_filename(att).lower()
        for pattern in (p.strip().lower() for p in self.patterns.split(",")):
            if not pattern:
                continue
            if pattern == "inline":
                if att.embedded:
                    return True
            elif "/" in pattern:
                if fnmatchcase(att.mime_type.lower(), pattern):
                    return True
            elif fnmatchcase(name, pattern):
                return True
        return False


def effective_filename(att: Attachment) -> str:
    """The file name, or one made from the MIME type (an attached mail has none)."""
    if att.filename:
        return att.filename
    return "message.eml" if att.mime_type == "message/rfc822" else ""


DEFAULT_RULES = (
    Rule("inline", Decision.SKIP, Scope.MARKED),
    Rule("*.p7s,*.asc,*.ics,*.vcf", Decision.SKIP, Scope.MARKED),
    Rule("*", Decision.DOCUMENT, Scope.MARKED),
    Rule("*.pdf,*.doc,*.docx,*.xls,*.xlsx,*.odt,*.ods,*.xml,*.zip,*.eml", Decision.DOCUMENT, Scope.BACKFILL),
)


def decide(
    att: Attachment,
    scope: Scope,
    rules: tuple[Rule, ...] | list[Rule] = DEFAULT_RULES,
    skipped: set[str] | frozenset[str] = frozenset(),
) -> Decision:
    """``skipped``: SHA256 sums the owner removed on purpose; they stay skipped."""
    if att.sha256 in skipped:
        return Decision.SKIP
    for rule in rules:
        if rule.scope in (scope, Scope.ALL) and rule.matches(att):
            return rule.decision
    return Decision.SKIP

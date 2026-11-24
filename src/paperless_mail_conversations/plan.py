"""Which attachments of a mail should be documents: policy applied, ZIPs expanded.

A ZIP is not a document itself: its files are (decided by the same policy).
A ZIP that cannot be read (encrypted, damaged, too large) stays one document.
"""

from __future__ import annotations

import io
import logging
import mimetypes
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .mail import Attachment
from .policy import Decision, Rule, Scope, decide

logger = logging.getLogger("paperless.mail_conversations")

MAX_ZIP_DEPTH = 3
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_BYTES = 500 * 1024 * 1024  # uncompressed, whole archive
_JUNK = ("__MACOSX/", ".DS_Store", "Thumbs.db", "desktop.ini")


def is_zip(att: Attachment) -> bool:
    return att.mime_type in ("application/zip", "application/x-zip-compressed") or (
        (att.filename or "").lower().endswith(".zip")
    )


def _entry_name(info: zipfile.ZipInfo) -> str:
    """The file name; names without the UTF-8 flag are tried as UTF-8, then as cp852 (Polish Windows)."""
    name = info.filename
    if not info.flag_bits & 0x800:
        raw = name.encode("cp437")
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = raw.decode("cp852")
    return PurePosixPath(name.replace("\\", "/")).name


def expand_zip(att: Attachment) -> list[Attachment] | None:
    """The files in the ZIP, or ``None`` when it cannot or should not be expanded."""
    try:
        with zipfile.ZipFile(io.BytesIO(att.content)) as z:
            infos = [
                i for i in z.infolist()
                if not i.is_dir() and not any(j in i.filename for j in _JUNK)
            ]
            if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
                logger.warning("[mail-conversations] %s: too large to expand", att.filename)
                return None
            if any(i.flag_bits & 0x1 for i in infos):
                return None  # encrypted
            out = []
            for info in infos:
                name = _entry_name(info)
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                out.append(Attachment(name, mime, z.read(info), embedded=False))
            return out
    except (zipfile.BadZipFile, NotImplementedError, OSError, RuntimeError, ValueError) as e:
        logger.warning("[mail-conversations] %s: cannot expand: %s", att.filename, e)
        return None


@dataclass
class Plan:
    files: list[Attachment] = field(default_factory=list)  # to become (or be linked as) documents
    mails: list[Attachment] = field(default_factory=list)  # attached mails, imported as mails

    @property
    def sha256s(self) -> set[str]:
        return {a.sha256 for a in self.files}


def plan_attachments(
    attachments: list[Attachment],
    scope: Scope,
    rules: list[Rule] | tuple[Rule, ...],
    skipped: set[str] | frozenset[str] = frozenset(),
) -> Plan:
    plan = Plan()

    def visit(atts: list[Attachment], depth: int) -> None:
        for att in atts:
            if decide(att, scope, rules, skipped) is not Decision.DOCUMENT:
                continue
            if att.is_message:
                plan.mails.append(att)
                continue
            if is_zip(att) and depth < MAX_ZIP_DEPTH:
                inner = expand_zip(att)
                if inner is not None:
                    visit(inner, depth + 1)
                    continue
            if att.sha256 not in plan.sha256s:
                plan.files.append(att)

    visit(attachments, 0)
    return plan

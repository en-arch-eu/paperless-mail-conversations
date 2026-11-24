"""Celery tasks chained after ``consume_file`` (found by Paperless' ``autodiscover_tasks``)."""

from __future__ import annotations

import logging

from celery import shared_task

from .importer import Context, add_links, after_mail, link_attachment
from . import fields as F

logger = logging.getLogger("paperless.mail_conversations")


def _document_id(result) -> int | None:
    """Document id from a ``consume_file`` result: new document or the duplicate it matched."""
    if not isinstance(result, dict):
        return None
    if "document_id" in result:
        return result["document_id"]
    if "duplicate_of" in result and not result.get("duplicate_in_trash"):
        return result["duplicate_of"]
    return None


@shared_task
def mail_consumed(result, ctx: Context, depth: int = 0, forwarded_by: int | None = None) -> None:
    doc_id = _document_id(result)
    if doc_id is None:
        logger.warning("[mail-conversations] mail not consumed: %r", result)
        return
    after_mail(doc_id, ctx, depth, forwarded_by)


@shared_task
def attachment_consumed(result, mail_doc_id: int, conversation: str | None = None) -> None:
    doc_id = _document_id(result)
    if doc_id is None:
        logger.warning("[mail-conversations] attachment of #%s not consumed: %r", mail_doc_id, result)
        return
    if "document_id" in result:
        add_links(doc_id, F.ATTACHMENT, [mail_doc_id])  # the consumer set it on the attachment only
    else:
        link_attachment(mail_doc_id, doc_id, conversation)


SYNC_LOCK = "mail-conversations:sync-lock"


@shared_task
def sync_conversations() -> str:
    """Import the marked conversations of all mail accounts (queued after every mail fetch)."""
    from django.core.cache import cache

    from .sync import sync_all

    if not cache.add(SYNC_LOCK, 1, timeout=30 * 60):
        return "Skipped: already running."
    try:
        return f"Queued {sync_all()} mail(s)."
    finally:
        cache.delete(SYNC_LOCK)

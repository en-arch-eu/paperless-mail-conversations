"""Import every message of the marked conversations of the Paperless mail accounts."""

from __future__ import annotations

import logging
import os

from django.utils import timezone

from .importer import Context, Source, ensure_fields, find_documents, import_mail
from . import fields as F
from .policy import Scope
from .providers import provider_for

logger = logging.getLogger("paperless.mail_conversations")


def storage_path_id() -> int | None:
    value = os.environ.get("PAPERLESS_MAIL_CONVERSATIONS_STORAGE_PATH")
    return int(value) if value else None


def sync_account(account) -> int:
    """Queue the messages of marked conversations that are not in Paperless; returns how many."""
    from paperless_mail.mail import get_mailbox, mailbox_login
    from paperless_mail.oauth import PaperlessMailOAuth2Manager

    ensure_fields()
    queued = 0
    with get_mailbox(account.imap_server, account.imap_port, account.imap_security) as M:
        if account.is_token and account.expiration is not None and account.expiration < timezone.now():
            if not PaperlessMailOAuth2Manager().refresh_account_oauth_token(account):
                logger.error("[mail-conversations] %s: cannot refresh the OAuth token", account)
                return 0
            account.refresh_from_db()
        provider = provider_for(M)
        if provider is None:
            logger.debug("[mail-conversations] %s: no conversation provider", account)
            return 0
        mailbox_login(M, account)
        provider.open(M)

        marked = provider.marked(M)
        conversations = {}
        for ref in marked:
            if ref.conversation_key is None:
                conversations[ref.message_key] = [ref]
            elif ref.conversation_key not in conversations:
                conversations[ref.conversation_key] = provider.conversation(M, ref)
        logger.info(
            "[mail-conversations] %s: %d marked message(s), %d conversation(s)",
            account, len(marked), len(conversations),
        )

        ctx = Context(
            account_name=account.name,
            account_address=account.username,
            scope=Scope.MARKED,
            owner_id=account.owner_id,
            storage_path_id=storage_path_id(),
        )
        for refs in conversations.values():
            missing = [r for r in refs if not find_documents(F.KEY, r.message_key)]
            if not missing:
                continue
            bodies = provider.fetch(M, missing)
            for ref in missing:
                raw = bodies.get(ref.uid)
                if raw is None:
                    logger.warning("[mail-conversations] %s: no body for UID %s", account, ref.uid)
                    continue
                source = Source(ref.message_key, ref.conversation_key, ref.web_link)
                if import_mail(raw, ctx, source) is None:
                    queued += 1
                provider.mark_imported(M, ref)
    return queued


def sync_all() -> int:
    from paperless_mail.models import MailAccount

    total = 0
    for account in MailAccount.objects.all():
        try:
            total += sync_account(account)
        except Exception:
            logger.exception("[mail-conversations] %s: sync failed", account)
    return total

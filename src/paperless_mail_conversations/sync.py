"""Mailbox side: marked conversations after every mail fetch, and the one-time backfill."""

from __future__ import annotations

import logging
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import PurePosixPath

from django.utils import timezone

from . import fields as F
from .importer import (
    Context, Source, custom_field, document_with_checksum, ensure_fields, find_documents, import_mail, is_queued,
    set_value,
)
from .mail import parse_mail
from .plan import plan_attachments
from .policy import Decision, Scope, decide
from .providers import provider_for

logger = logging.getLogger("paperless.mail_conversations")


def account_context(account, scope: Scope) -> Context:
    return Context(
        account_name=account.name,
        account_address=account.username,
        scope=scope,
        owner_id=account.owner_id,
    )


@contextmanager
def open_mailbox(account):
    """Logged-in mailbox and its provider (``None`` when no provider supports it)."""
    from paperless_mail.mail import get_mailbox, mailbox_login
    from paperless_mail.oauth import PaperlessMailOAuth2Manager

    with get_mailbox(account.imap_server, account.imap_port, account.imap_security) as M:
        if account.is_token and account.expiration is not None and account.expiration < timezone.now():
            if not PaperlessMailOAuth2Manager().refresh_account_oauth_token(account):
                raise RuntimeError(f"{account}: cannot refresh the OAuth token")
            account.refresh_from_db()
        provider = provider_for(M)
        if provider is not None:
            mailbox_login(M, account)
            provider.open(M)
        yield M, provider


def known_keys() -> set[str]:
    from documents.models import CustomFieldInstance

    return set(
        CustomFieldInstance.objects.filter(field=custom_field(F.KEY), document__deleted_at__isnull=True)
        .values_list("value_text", flat=True)
    )


WATCH_QUERY = "newer_than:7d"  # new messages in conversations already imported
TIME_BUDGET = 10 * 60  # seconds per sync, keeps the worker free for consuming; Paperless kills tasks after 30 min


def backfill_keys() -> set[str]:
    """Keys of mails imported with the backfill policy."""
    from documents.models import CustomFieldInstance

    scope = custom_field(F.SCOPE)
    option = next(o["id"] for o in scope.extra_data["select_options"] if o["label"] == Scope.BACKFILL.value)
    docs = CustomFieldInstance.objects.filter(field=scope, value_select=option, document__deleted_at__isnull=True)
    return set(
        CustomFieldInstance.objects.filter(field=custom_field(F.KEY), document_id__in=docs.values("document_id"))
        .values_list("value_text", flat=True)
    )


def _import(M, provider, account, ctx: Context, refs: list) -> int:
    """Fetch and queue ``refs``; returns how many were queued."""
    queued = 0
    bodies = provider.fetch(M, refs)
    for ref in refs:
        raw = bodies.get(ref.uid)
        if raw is None:
            logger.warning("[mail-conversations] %s: no body for UID %s", account, ref.uid)
            continue
        if import_mail(raw, ctx, Source(ref.message_key, ref.conversation_key, ref.web_link)) is None:
            queued += 1
        provider.mark_imported(M, ref)
    return queued


def sync_account(account, deadline: float | None = None) -> int:
    """Queue the messages of marked conversations that are not in Paperless; returns how many.

    A conversation with a marked message not in Paperless yet is looked up in full
    (one search per conversation) and queued at once; past ``deadline`` the rest waits
    for the next sync. New messages in conversations already imported are found with
    one search of the recent messages."""
    from .models import current_rules
    from .reconcile import reconcile_mail

    ensure_fields()
    with open_mailbox(account) as (M, provider):
        if provider is None:
            logger.debug("[mail-conversations] %s: no conversation provider", account)
            return 0
        marked = provider.marked(M)
        known = known_keys()

        def done(ref) -> bool:
            return ref.message_key in known or is_queued(ref.message_key)

        conversations: dict[str, list] = {}  # conversation -> its marked messages
        for ref in marked:
            conversations.setdefault(ref.conversation_key or ref.message_key, []).append(ref)
        new = {key: refs for key, refs in conversations.items() if not all(done(r) for r in refs)}
        logger.info(
            "[mail-conversations] %s: %d marked message(s), %d conversation(s), %d new",
            account, len(marked), len(conversations), len(new),
        )
        ctx = account_context(account, Scope.MARKED)
        queued = 0

        # came with the backfill, now in a marked conversation: the marked policy applies
        backfilled = backfill_keys()
        for ref in marked:
            if ref.message_key in backfilled:
                for doc_id in find_documents(F.KEY, ref.message_key):
                    set_value(doc_id, F.SCOPE, Scope.MARKED.value)
                    for line in reconcile_mail(doc_id, current_rules()):
                        logger.info("[mail-conversations] %s", line)

        try:
            recent = provider.search(M, WATCH_QUERY)
        except NotImplementedError:
            recent = []
        replies = [
            r for r in recent
            if r.conversation_key in conversations and r.conversation_key not in new and not done(r)
        ]
        if replies:
            queued += _import(M, provider, account, ctx, replies)

        for i, refs in enumerate(new.values()):
            if deadline is not None and time.monotonic() > deadline:
                logger.info("[mail-conversations] %s: time is up, %d conversation(s) left for the next sync", account, len(new) - i)
                break
            members = provider.conversation(M, refs[0]) if refs[0].conversation_key else refs
            missing = [r for r in members if not done(r)]
            if missing:
                queued += _import(M, provider, account, ctx, missing)
    return queued


def sync_all() -> int:
    from paperless_mail.models import MailAccount

    from .heal import heal

    deadline = time.monotonic() + TIME_BUDGET
    try:
        heal(deadline)  # first: the lost work is older than anything queued now
    except Exception:
        logger.exception("[mail-conversations] follow-up check failed")
    total = 0
    for account in MailAccount.objects.all():
        try:
            total += sync_account(account, deadline)
        except Exception:
            logger.exception("[mail-conversations] %s: sync failed", account)
    return total


def backfill_account(account, query: str, limit: int | None, dry_run: bool, report=print) -> Counter:
    """Import the messages matching ``query`` that are not in Paperless yet (oldest first),
    with the backfill policy. ``dry_run``: only count, nothing is written anywhere."""
    from .models import current_rules

    ensure_fields()
    stats: Counter = Counter()
    rules = current_rules()
    with open_mailbox(account) as (M, provider):
        if provider is None:
            raise RuntimeError(f"{account}: no conversation provider")
        refs = provider.search(M, query)
        known = known_keys()
        missing = [r for r in refs if r.message_key not in known]
        stats["found"], stats["already in Paperless"] = len(refs), len(refs) - len(missing)
        if limit is not None:
            missing = missing[:limit]
        ctx = account_context(account, Scope.BACKFILL)
        for i in range(0, len(missing), 50):
            chunk = missing[i : i + 50]
            bodies = provider.fetch(M, chunk)
            for ref in chunk:
                raw = bodies.get(ref.uid)
                if raw is None:
                    stats["no body"] += 1
                    continue
                stats["mails"] += 1
                if dry_run:
                    mail = parse_mail(raw)
                    plan = plan_attachments(mail.attachments, Scope.BACKFILL, rules)
                    stats["attachments in mails"] += len(mail.attachments)
                    for att in mail.attachments:
                        if decide(att, Scope.BACKFILL, rules) is Decision.SKIP:
                            kind = "embedded image" if att.embedded else (PurePosixPath(att.filename or "").suffix.lower() or att.mime_type)
                            stats[f"skipped: {kind}"] += 1
                    stats["attached mails"] += len(plan.mails)
                    for att in plan.files:
                        stats["files linked (in Paperless)" if document_with_checksum(att.sha256) else "files imported (new)"] += 1
                    report(f"  {mail.date:%Y-%m-%d} {mail.subject[:70]!r}: {len(plan.files)} file(s)" if mail.date else f"  {mail.subject[:70]!r}")
                    continue
                if import_mail(raw, ctx, Source(ref.message_key, ref.conversation_key, ref.web_link)) is None:
                    stats["queued"] += 1
                provider.mark_imported(M, ref)
    return stats

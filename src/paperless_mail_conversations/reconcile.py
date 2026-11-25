"""Re-apply the attachment policy to mails already in Paperless (``mail_conversations_reconcile``).

The original ``.eml`` of each mail holds every attachment, so a changed policy
can be applied without the mailbox:

- an attachment that should be a document and is not linked: linked, restored
  from the trash or imported;
- a document created from an attachment (``Mail: z załącznika``) that should no
  longer be one: moved to the trash, unless another mail still needs it.
  Documents that were in Paperless before (only linked) are never touched.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path

from . import fields as F
from .importer import Context, Source, attach_file, checksums, custom_field, find_documents, get_value, import_mail
from .mail import parse_mail
from .plan import Plan, plan_attachments
from .policy import Rule, Scope

logger = logging.getLogger("paperless.mail_conversations")

# set while reconcile trashes documents: such deletions are policy, not the owner's decision
POLICY_DELETE = contextvars.ContextVar("mail_conversations_policy_delete", default=False)


@contextmanager
def policy_delete():
    token = POLICY_DELETE.set(True)
    try:
        yield
    finally:
        POLICY_DELETE.reset(token)


def mail_documents() -> list[int]:
    """Ids of the mail documents (those with ``Mail: klucz``), oldest first."""
    from documents.models import Document

    return list(
        Document.objects.filter(custom_fields__field=custom_field(F.KEY)).order_by("pk").values_list("pk", flat=True).distinct()
    )


def mail_context(doc) -> Context:
    from paperless_mail.models import MailAccount

    name = get_value(doc.pk, F.ACCOUNT) or ""
    account = MailAccount.objects.filter(name=name).first()
    scope = get_value(doc.pk, F.SCOPE)
    return Context(
        account_name=name,
        account_address=account.username if account else "",
        scope=Scope(scope) if scope else Scope.MARKED,
        owner_id=doc.owner_id,
    )


def mail_plan(doc, rules: list[Rule]) -> tuple[Context, Plan, object]:
    mail = parse_mail(Path(doc.source_path).read_bytes())
    ctx = mail_context(doc)
    skipped = F.parse_skipped(get_value(doc.pk, F.SKIPPED))
    return ctx, plan_attachments(mail.attachments, ctx.scope, rules, skipped), mail


def _matches(pattern: str | None, filename: str | None) -> bool:
    return pattern is None or fnmatchcase((filename or "").lower(), pattern.lower())


def reconcile_mail(doc_id: int, rules: list[Rule], pattern: str | None = None, dry_run: bool = False) -> list[str]:
    """Changes for one mail (made unless ``dry_run``), one line each."""
    from documents.models import Document

    doc = Document.objects.get(pk=doc_id)
    ctx, plan, _ = mail_plan(doc, rules)
    conversation = get_value(doc_id, F.CONVERSATION)
    linked = {d.pk: d for d in Document.objects.filter(pk__in=get_value(doc_id, F.ATTACHMENT) or [])}
    linked_sha = {c for d in linked.values() for c in checksums(d)}
    changes = []

    for att in plan.files:
        if att.sha256 in linked_sha or not _matches(pattern, att.filename):
            continue
        done = "to import or link" if dry_run else attach_file(doc_id, att, ctx, conversation)
        changes.append(f"#{doc_id}: {att.filename}: {done}")

    for att in plan.mails:
        inner = parse_mail(att.content)
        known = inner.message_id and find_documents(F.MESSAGE_ID, inner.message_id)
        if dry_run:
            if not known:
                changes.append(f"#{doc_id}: attached mail {inner.subject!r}: to import")
        elif import_mail(att.content, ctx, Source(), 1, forwarded_by=doc_id) is None:
            changes.append(f"#{doc_id}: attached mail {inner.subject!r}: queued")

    for d in linked.values():
        if checksums(d) & set(plan.sha256s) or not get_value(d.pk, F.FROM_ATTACHMENT):
            continue
        if not _matches(pattern, d.original_filename):
            continue
        others = [m for m in get_value(d.pk, F.ATTACHMENT) or [] if m != doc_id]
        needed_by = [
            m.pk for m in Document.objects.filter(pk__in=others)
            if get_value(m.pk, F.KEY) and checksums(d) & set(mail_plan(m, rules)[1].sha256s)
        ]
        if needed_by:
            changes.append(f"#{doc_id}: #{d.pk} {d.original_filename}: kept, needed by #{needed_by[0]}")
            continue
        if not dry_run:
            with policy_delete():
                d.delete()
        changes.append(f"#{doc_id}: #{d.pk} {d.original_filename}: {'to trash' if dry_run else 'moved to the trash'}")
    return changes


def on_document_soft_delete(sender, instance, **kwargs) -> None:
    """The owner deleted a document made from an attachment: record its SHA256
    in ``Mail: pominięte załączniki`` of its mails, so reconcile does not bring it back."""
    if POLICY_DELETE.get():
        return
    try:
        from documents.models import CustomFieldInstance

        fields = {
            i.field_id: i
            for i in CustomFieldInstance.global_objects.filter(
                document_id=instance.pk, field__in=[custom_field(F.FROM_ATTACHMENT), custom_field(F.ATTACHMENT)]
            )
        }
        flag = fields.get(custom_field(F.FROM_ATTACHMENT).pk)
        links = fields.get(custom_field(F.ATTACHMENT).pk)
        if not (flag and flag.value_bool and links and links.value_document_ids):
            return
        from .importer import set_value

        for mail_id in links.value_document_ids:
            text = get_value(mail_id, F.SKIPPED)
            new = F.add_skipped(text, instance.checksum)
            if new != (text or ""):
                set_value(mail_id, F.SKIPPED, new)
                logger.info("[mail-conversations] #%s deleted: skipped from now on for mail #%s", instance.pk, mail_id)
    except Exception:
        # never block a deletion
        logger.exception("[mail-conversations] cannot record deleted attachment #%s", instance.pk)

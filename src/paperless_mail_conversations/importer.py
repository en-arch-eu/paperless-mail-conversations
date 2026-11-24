"""Import a mail into Paperless and link it to attachments, replies and forwards.

Uses internal Paperless APIs (``consume_file``, ``DocumentMetadataOverrides``,
``reflect_doclinks``); run the tests after every Paperless upgrade.

Flow: ``import_mail`` queues ``consume_file`` for the ``.eml`` chained with
``tasks.mail_consumed``, which calls ``after_mail``. That links the mail and
queues its attachments the same way (``consume_file`` -> ``tasks.attachment_consumed``).
Chaining instead of the ``document_consumption_finished`` signal: the chained
task runs after the consumer's transaction is committed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from celery import chain
from django.conf import settings
from django.db import transaction
from django.utils.crypto import get_random_string

from . import fields as F
from .fields import FieldDef
from .links import MAX_DEPTH, Kind, relation
from .mail import Attachment, Mail, parse_mail
from .policy import Decision, Rule, Scope, decide

logger = logging.getLogger("paperless.mail_conversations")


@dataclass(frozen=True)
class Context:
    """Where a mail comes from and how its documents are filed (pickled into tasks)."""

    account_name: str
    account_address: str
    scope: Scope = Scope.MARKED
    owner_id: int | None = None
    storage_path_id: int | None = None


@dataclass(frozen=True)
class Source:
    """Provider data of one message; empty for a mail read from a file or an attachment."""

    message_key: str | None = None
    conversation_key: str | None = None
    web_link: str | None = None


# --- custom fields ---------------------------------------------------------


def custom_field(fd: FieldDef):
    """The Paperless field for ``fd``, created when missing."""
    from documents.models import CustomField

    cf, created = CustomField.objects.get_or_create(name=fd.name, defaults={"data_type": fd.data_type})
    if cf.data_type != fd.data_type:
        raise RuntimeError(f"custom field {fd.name!r} has type {cf.data_type}, expected {fd.data_type}")
    if fd.select_options:
        options = (cf.extra_data or {}).get("select_options") or []
        labels = {o["label"] for o in options}
        missing = [label for label in fd.select_options if label not in labels]
        if missing:
            options += [{"id": get_random_string(16), "label": label} for label in missing]
            cf.extra_data = {**(cf.extra_data or {}), "select_options": options}
            cf.save(update_fields=["extra_data"])
    if created:
        logger.info("[mail-conversations] created custom field %r", fd.name)
    return cf


def ensure_fields() -> None:
    for fd in F.ALL_FIELDS:
        custom_field(fd)


def _stored_value(fd: FieldDef, cf, value):
    if fd.data_type == "select":
        return next(o["id"] for o in cf.extra_data["select_options"] if o["label"] == value)
    return value


def _value_name(fd: FieldDef) -> str:
    from documents.models import CustomFieldInstance

    return CustomFieldInstance.get_value_field_name(fd.data_type)


def overrides_fields(values: dict[FieldDef, object]) -> dict[int, object]:
    """``DocumentMetadataOverrides.custom_fields``: field id -> stored value."""
    out = {}
    for fd, value in values.items():
        cf = custom_field(fd)
        out[cf.pk] = _stored_value(fd, cf, value)
    return out


def get_value(doc_id: int, fd: FieldDef):
    from documents.models import CustomFieldInstance

    inst = CustomFieldInstance.objects.filter(document_id=doc_id, field=custom_field(fd)).first()
    return getattr(inst, _value_name(fd)) if inst else None


def set_value(doc_id: int, fd: FieldDef, value) -> None:
    from documents.models import CustomFieldInstance

    cf = custom_field(fd)
    CustomFieldInstance.objects.update_or_create(
        document_id=doc_id, field=cf, defaults={_value_name(fd): _stored_value(fd, cf, value)}
    )


def find_documents(fd: FieldDef, value: str) -> list[int]:
    """Ids of documents whose field ``fd`` equals ``value``."""
    from documents.models import Document

    return list(
        Document.objects.filter(
            custom_fields__field=custom_field(fd),
            **{f"custom_fields__{_value_name(fd)}": value},
        )
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()
    )


def add_links(doc_id: int, fd: FieldDef, target_ids: list[int]) -> None:
    """Add document links on ``doc_id`` and the same links back on the targets."""
    from documents.bulk_edit import reflect_doclinks
    from documents.models import CustomFieldInstance, Document

    target_ids = [t for t in target_ids if t != doc_id]
    if not target_ids:
        return
    cf = custom_field(fd)
    with transaction.atomic():
        # lock every document involved: concurrent attachment tasks update the same mail
        list(Document.objects.select_for_update().filter(pk__in=[doc_id, *target_ids]).order_by("pk"))
        inst = CustomFieldInstance.objects.filter(document_id=doc_id, field=cf).first()
        current = list(inst.value_document_ids or []) if inst else []
        wanted = current + [t for t in target_ids if t not in current]
        reflect_doclinks(Document.objects.get(pk=doc_id), cf, wanted)  # the other side
        if inst is None or wanted != current:
            CustomFieldInstance.objects.update_or_create(
                document_id=doc_id, field=cf, defaults={"value_document_ids": wanted}
            )


# --- documents -------------------------------------------------------------


def document_with_checksum(sha256: str) -> int | None:
    """A document (not in the trash) whose original has this SHA256; versions resolve to their root."""
    from documents.models import Document

    doc = Document.objects.filter(checksum=sha256).order_by("pk").first()
    if doc is None:
        return None
    return doc.root_document_id or doc.pk


def _consume(content: bytes, filename: str, overrides_kwargs: dict, then):
    """Queue ``consume_file`` for ``content``, chained with the task signature ``then``."""
    import pathvalidate
    from documents.data_models import ConsumableDocument, DocumentMetadataOverrides, DocumentSource
    from documents.tasks import consume_file

    filename = pathvalidate.sanitize_filename(unicodedata.normalize("NFC", filename)) or "attachment"
    settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    # a file, not a directory: the consumer deletes the file and nothing is left behind
    fd, name = tempfile.mkstemp(dir=settings.SCRATCH_DIR, prefix="mail-conversations-", suffix=Path(filename).suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    path = Path(name)
    input_doc = ConsumableDocument(source=DocumentSource.ConsumeFolder, original_file=path)
    overrides = DocumentMetadataOverrides(filename=filename, **overrides_kwargs)
    transaction.on_commit(lambda: chain(consume_file.s(input_doc=input_doc, overrides=overrides), then).delay())


def import_mail(raw: bytes, ctx: Context, source: Source = Source(), depth: int = 0, forwarded_by: int | None = None) -> int | None:
    """Import one mail. Returns the document id when the mail is already in
    Paperless (it is then only linked), ``None`` when it was queued."""
    from .tasks import mail_consumed

    mail = parse_mail(raw)
    sha = hashlib.sha256(raw).hexdigest()
    key = source.message_key or mail.message_id or f"sha256:{sha}"

    known = find_documents(F.KEY, key) or (find_documents(F.MESSAGE_ID, mail.message_id) if mail.message_id else [])
    if known:
        doc_id = known[0]
        logger.info("[mail-conversations] %s already imported as #%s", key, doc_id)
        if source.message_key and get_value(doc_id, F.KEY) != source.message_key:
            # imported before without the provider (from a file, as an attachment): now it has one
            set_value(doc_id, F.KEY, source.message_key)
            for fd, value in ((F.CONVERSATION, source.conversation_key), (F.LINK, source.web_link)):
                if value and not get_value(doc_id, fd):
                    set_value(doc_id, fd, value)
        if forwarded_by:
            add_links(forwarded_by, F.FORWARD, [doc_id])
        return doc_id

    # the next sync may run before this mail is consumed
    from django.core.cache import cache

    if not cache.add(f"mail-conversations:queued:{key}", 1, timeout=3600):
        logger.info("[mail-conversations] %s already queued", key)
        return None

    values = F.header_fields(
        mail,
        account_name=ctx.account_name,
        account_address=ctx.account_address,
        message_key=key,
        conversation_key=source.conversation_key,
        web_link=source.web_link,
    )
    same_file = document_with_checksum(sha)
    if same_file:
        # the .eml is already a document (e.g. a file from disk): it becomes the mail
        logger.info("[mail-conversations] %s: file already in Paperless as #%s, adopting it", key, same_file)
        for fd, value in values.items():
            set_value(same_file, fd, value)
        after_mail(same_file, ctx, depth, forwarded_by)
        return same_file

    title = mail.subject or "(no subject)"
    _consume(
        raw,
        f"{title[:100]}.eml",
        {
            "title": title[:128],
            "created": mail.date.date() if mail.date else None,
            "custom_fields": overrides_fields(values),
            "owner_id": ctx.owner_id,
            "storage_path_id": ctx.storage_path_id,
        },
        mail_consumed.s(ctx=ctx, depth=depth, forwarded_by=forwarded_by),
    )
    logger.info("[mail-conversations] %s queued: %s", key, title)
    return None


def _related_kind(raw: bytes, parent_message_id: str) -> Kind | None:
    rel = relation(parse_mail(raw))
    return rel.kind if rel and rel.message_id == parent_message_id else None


def _field_for(kind: Kind) -> FieldDef:
    return F.REPLY if kind is Kind.REPLY else F.FORWARD


def after_mail(doc_id: int, ctx: Context, depth: int = 0, forwarded_by: int | None = None, rules: list[Rule] | None = None) -> None:
    """Link a mail document: forwarded mail, parent, children, attachments."""
    from documents.models import Document

    from .models import current_rules

    doc = Document.objects.get(pk=doc_id)
    raw = Path(doc.source_path).read_bytes()
    mail = parse_mail(raw)

    if forwarded_by:
        add_links(forwarded_by, F.FORWARD, [doc_id])

    rel = relation(mail)
    if rel:
        parents = [p for p in find_documents(F.MESSAGE_ID, rel.message_id) if p != doc_id]
        add_links(doc_id, _field_for(rel.kind), parents)

    # replies and forwards imported before this mail
    if mail.message_id:
        for child in find_documents(F.IN_REPLY_TO, mail.message_id):
            if child == doc_id:
                continue
            kind = _related_kind(Path(Document.objects.get(pk=child).source_path).read_bytes(), mail.message_id)
            if kind:
                add_links(child, _field_for(kind), [doc_id])

    handle_attachments(doc_id, mail, ctx, depth, current_rules() if rules is None else rules)


def handle_attachments(doc_id: int, mail: Mail, ctx: Context, depth: int, rules: list[Rule]) -> None:
    from .tasks import attachment_consumed

    skipped = F.parse_skipped(get_value(doc_id, F.SKIPPED))
    conversation = get_value(doc_id, F.CONVERSATION)
    for att in mail.attachments:
        if decide(att, ctx.scope, rules, skipped) is not Decision.DOCUMENT:
            continue
        if att.is_message:
            if depth + 1 > MAX_DEPTH:
                logger.warning("[mail-conversations] #%s: attached mail deeper than %s, skipped", doc_id, MAX_DEPTH)
                continue
            import_mail(att.content, ctx, Source(), depth + 1, forwarded_by=doc_id)
            continue
        existing = document_with_checksum(att.sha256)
        if existing:
            link_attachment(doc_id, existing, conversation)
            continue
        values: dict[FieldDef, object] = {F.ATTACHMENT: [doc_id], F.FROM_ATTACHMENT: True}
        if conversation:
            values[F.CONVERSATION] = conversation
        _consume(
            att.content,
            _attachment_filename(att),
            {
                "custom_fields": overrides_fields(values),
                "owner_id": ctx.owner_id,
                "storage_path_id": ctx.storage_path_id,
            },
            attachment_consumed.s(mail_doc_id=doc_id, conversation=conversation),
        )


def _attachment_filename(att: Attachment) -> str:
    if att.filename:
        return att.filename
    import mimetypes

    return "attachment" + (mimetypes.guess_extension(att.mime_type) or "")


def link_attachment(mail_doc_id: int, attachment_doc_id: int, conversation: str | None) -> None:
    add_links(mail_doc_id, F.ATTACHMENT, [attachment_doc_id])
    if conversation and not get_value(attachment_doc_id, F.CONVERSATION):
        set_value(attachment_doc_id, F.CONVERSATION, conversation)

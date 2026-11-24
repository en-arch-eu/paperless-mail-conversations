"""Django app for Paperless-ngx.

Enable with ``PAPERLESS_APPS=paperless_mail_conversations.apps.MailConversationsConfig``.
After every run of Paperless' mail fetch (``process_mail_accounts``, every
10 minutes by default) the app queues ``tasks.sync_conversations``.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

from ._version import __version__

logger = logging.getLogger("paperless.mail_conversations")


class MailConversationsConfig(AppConfig):
    name = "paperless_mail_conversations"
    label = "paperless_mail_conversations"
    verbose_name = "Mail conversations"

    def ready(self) -> None:
        from celery.signals import task_postrun

        from django_softdelete.signals import post_soft_delete
        from documents.models import Document

        from .reconcile import on_document_soft_delete

        task_postrun.connect(_after_mail_fetch, weak=False, dispatch_uid="mail_conversations_after_fetch")
        post_soft_delete.connect(on_document_soft_delete, sender=Document, weak=False, dispatch_uid="mail_conversations_soft_delete")
        logger.info("[mail-conversations] loaded, version %s", __version__)


MAIL_FETCH_TASK = "paperless_mail.tasks.process_mail_accounts"


def _after_mail_fetch(sender=None, task=None, **kwargs) -> None:
    if getattr(task, "name", None) == MAIL_FETCH_TASK:
        from .tasks import sync_conversations

        sync_conversations.delay()

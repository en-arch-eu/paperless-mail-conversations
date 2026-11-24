"""Django app for Paperless-ngx.

Enable with ``PAPERLESS_APPS=paperless_mail_conversations.apps.MailConversationsConfig``.
Signal handlers, tasks and the policy model are added in the integration step.
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
        logger.info("[mail-conversations] loaded, version %s", __version__)

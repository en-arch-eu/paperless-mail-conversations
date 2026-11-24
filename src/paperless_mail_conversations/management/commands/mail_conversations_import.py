"""Import ``.eml`` files as mails (without a conversation provider)."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from paperless_mail_conversations.importer import Context, ensure_fields, import_mail
from paperless_mail_conversations.policy import Scope


class Command(BaseCommand):
    help = "Import .eml files as mail documents linked to their attachments, replies and forwards."

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+", type=Path)
        parser.add_argument("--account", default="file", help="value of 'Mail: konto'")
        parser.add_argument("--address", default="", help="the account's own address (sets 'Mail: kierunek')")
        parser.add_argument("--scope", choices=[s.value for s in Scope if s is not Scope.ALL], default=Scope.MARKED.value)
        parser.add_argument("--owner", type=int, help="owner user id")
        parser.add_argument("--storage-path", type=int, help="storage path id")

    def handle(self, *args, **opts):
        ensure_fields()
        ctx = Context(opts["account"], opts["address"], Scope(opts["scope"]), opts["owner"], opts["storage_path"])
        for path in opts["files"]:
            doc_id = import_mail(path.read_bytes(), ctx)
            self.stdout.write(f"{path}: " + (f"already #{doc_id}" if doc_id else "queued"))

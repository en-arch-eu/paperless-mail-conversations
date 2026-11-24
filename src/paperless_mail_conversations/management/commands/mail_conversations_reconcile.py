"""Re-apply the attachment policy to the mails already in Paperless."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from paperless_mail_conversations.models import current_rules
from paperless_mail_conversations.reconcile import mail_documents, reconcile_mail


class Command(BaseCommand):
    help = (
        "Compare each mail's attachments (from its .eml) with the attachment policy: import or link "
        "what should be a document, move to the trash documents made from attachments that should not be."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="only list the changes")
        parser.add_argument("--pattern", help="only attachments whose file name matches (e.g. '*.jpg')")
        parser.add_argument("--document", type=int, action="append", help="only this mail document (repeatable)")

    def handle(self, *args, **opts):
        rules = current_rules()
        total = 0
        for doc_id in opts["document"] or mail_documents():
            for line in reconcile_mail(doc_id, rules, opts["pattern"], opts["dry_run"]):
                self.stdout.write(line)
                total += 1
        self.stdout.write(f"{total} change(s){' (dry run)' if opts['dry_run'] else ''}")

"""One-time import of old mails (with the backfill attachment policy)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from paperless_mail_conversations.sync import backfill_account


class Command(BaseCommand):
    help = (
        "Import the mails matching a search query that are not in Paperless yet, oldest first, "
        "linking their attachments to documents already in Paperless (same SHA256). "
        "Conversations are not watched; the messages get the 'imported' label."
    )

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, help="mail account name")
        parser.add_argument("--query", default="has:attachment", help="provider search query (Gmail syntax)")
        parser.add_argument("--limit", type=int, help="at most this many mails")
        parser.add_argument("--dry-run", action="store_true", help="only count; nothing is written to Paperless or the mailbox")

    def handle(self, *args, **opts):
        from paperless_mail.models import MailAccount

        account = MailAccount.objects.get(name=opts["account"])
        report = self.stdout.write if opts["verbosity"] >= 2 else (lambda line: None)
        stats = backfill_account(account, opts["query"], opts["limit"], opts["dry_run"], report)
        for name, count in stats.items():
            self.stdout.write(f"{name}: {count}")

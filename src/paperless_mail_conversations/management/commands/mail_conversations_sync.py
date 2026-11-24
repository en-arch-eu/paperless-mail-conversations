"""Import the marked conversations now (normally runs after every mail fetch)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from paperless_mail_conversations.sync import sync_account


class Command(BaseCommand):
    help = "Import every message of the marked conversations of the mail accounts."

    def add_arguments(self, parser):
        parser.add_argument("--account", help="mail account name (default: all)")

    def handle(self, *args, **opts):
        from paperless_mail.models import MailAccount

        accounts = MailAccount.objects.all()
        if opts["account"]:
            accounts = accounts.filter(name=opts["account"])
        for account in accounts:
            self.stdout.write(f"{account.name}: queued {sync_account(account)}")

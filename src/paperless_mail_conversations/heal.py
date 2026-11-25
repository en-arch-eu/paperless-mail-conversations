"""Finish the follow-up work of recent mails after Redis lost its data.

The work after a mail is consumed runs as queued Celery tasks: the mail's own
follow-up (links, attachments), each attachment's ``consume_file`` and the task
linking it back to the mail. The queue lives in Redis, and so does the cache;
when Redis loses its data (an app restart without persistence), queued tasks
are gone: attachments are never imported and links stay one-sided.

A cache key that never expires tells when that happened: if it is missing,
the follow-up (``after_mail``) runs again for every mail added in the
``WINDOW`` before. ``after_mail`` only adds what is missing: it links the
attachments already in Paperless (also the other side of a link) and imports
the rest; attachments removed by hand are in ``Mail: pominięte załączniki``
and stay out. Mails lost before they were consumed are imported again by the
sync (their "queued" marker went with the cache).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from . import fields as F
from .importer import after_mail, custom_field

logger = logging.getLogger("paperless.mail_conversations")

ALIVE = "mail-conversations:alive"  # missing: Redis lost its data, and the queue with it
STATE = "mail-conversations:heal"  # {"until": ISO time, "after": last mail document id done}
WINDOW = timedelta(hours=48)  # longer than any consume queue so far (about 6 h for 1900 mails)


def heal(deadline: float) -> int:
    """Re-run the follow-up of recent mails if Redis lost its data; continues in the
    next sync when ``deadline`` (``time.monotonic()``) comes first. Returns mails done."""
    from django.core.cache import cache
    from django.utils import timezone
    from documents.models import Document

    from .reconcile import mail_context

    if cache.add(ALIVE, 1, timeout=None):
        cache.set(STATE, {"until": timezone.now().isoformat(), "after": 0}, timeout=None)
        logger.info("[mail-conversations] the cache was empty (Redis restarted?): checking mails of the last %s", WINDOW)
    state = cache.get(STATE)
    if not state:
        return 0

    until = datetime.fromisoformat(state["until"])
    # ids first: the follow-up closes the database connection, an open cursor would break
    mails = list(
        Document.objects.filter(custom_fields__field=custom_field(F.KEY), added__gte=until - WINDOW, added__lt=until, pk__gt=state["after"])
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()
    )
    done = 0
    for doc_id in mails:
        if time.monotonic() > deadline:
            logger.info("[mail-conversations] time is up, mails after #%s are checked in the next sync", state["after"])
            return done
        try:
            after_mail(doc_id, mail_context(Document.objects.get(pk=doc_id)))
        except Exception:
            logger.exception("[mail-conversations] #%s: follow-up failed", doc_id)
        state["after"] = doc_id
        cache.set(STATE, state, timeout=None)
        done += 1
    cache.delete(STATE)
    logger.info("[mail-conversations] follow-up checked for %s mail(s) up to #%s", done, state["after"])
    return done

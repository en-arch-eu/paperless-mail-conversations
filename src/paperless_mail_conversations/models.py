"""Attachment policy rules, edited in the Django admin (``/admin``)."""

from __future__ import annotations

from django.db import models

from .policy import Decision, Rule, Scope


class AttachmentRule(models.Model):
    position = models.PositiveIntegerField(default=100, help_text="Lower first; the first matching rule decides.")
    patterns = models.CharField(
        max_length=512,
        help_text="Comma separated: file name glob (*.pdf), MIME glob (image/*) or the word inline.",
    )
    decision = models.CharField(max_length=16, choices=[(d.value, d.value) for d in Decision])
    scope = models.CharField(max_length=16, choices=[(s.value, s.value) for s in Scope])
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.position}: {self.patterns} -> {self.decision} ({self.scope})"

    def as_rule(self) -> Rule:
        return Rule(self.patterns, Decision(self.decision), Scope(self.scope))


def current_rules() -> list[Rule]:
    return [r.as_rule() for r in AttachmentRule.objects.filter(enabled=True)]

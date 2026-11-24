from django.contrib import admin

from .models import AttachmentRule


@admin.register(AttachmentRule)
class AttachmentRuleAdmin(admin.ModelAdmin):
    list_display = ("position", "patterns", "decision", "scope", "enabled")
    list_editable = ("patterns", "decision", "scope", "enabled")
    list_display_links = ("position",)
    list_filter = ("scope", "decision", "enabled")

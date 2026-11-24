from django.db import migrations, models

from paperless_mail_conversations.policy import DEFAULT_RULES, Decision, Scope


def add_default_rules(apps, schema_editor):
    AttachmentRule = apps.get_model("paperless_mail_conversations", "AttachmentRule")
    AttachmentRule.objects.bulk_create(
        AttachmentRule(position=(i + 1) * 10, patterns=r.patterns, decision=r.decision.value, scope=r.scope.value)
        for i, r in enumerate(DEFAULT_RULES)
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AttachmentRule",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=100, help_text="Lower first; the first matching rule decides.")),
                ("patterns", models.CharField(max_length=512, help_text="Comma separated: file name glob (*.pdf), MIME glob (image/*) or the word inline.")),
                ("decision", models.CharField(max_length=16, choices=[(d.value, d.value) for d in Decision])),
                ("scope", models.CharField(max_length=16, choices=[(s.value, s.value) for s in Scope])),
                ("enabled", models.BooleanField(default=True)),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.RunPython(add_default_rules, migrations.RunPython.noop),
    ]

# Print documents with their custom fields:
#   docker exec <webserver> python3 manage.py shell -c "exec(open('/tmp/dump.py').read())"
from documents.models import CustomFieldInstance, Document

for d in Document.objects.order_by("pk"):
    print(f"#{d.pk} {d.title!r} {d.mime_type} tags={[t.name for t in d.tags.all()]}")
    for i in CustomFieldInstance.objects.filter(document=d).select_related("field").order_by("field__pk"):
        print("    ", i.field.name, "=", repr(i.value))

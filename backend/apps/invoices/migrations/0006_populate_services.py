from django.db import migrations


def normalize_for_match(name: str) -> str:
    return " ".join(name.strip().upper().split())


def populate_services(apps, schema_editor):
    LineItem = apps.get_model("invoices", "LineItem")
    Service = apps.get_model("invoices", "Service")
    ServiceAlias = apps.get_model("invoices", "ServiceAlias")

    user_services: dict[tuple[int, str], int] = {}

    for li in LineItem.objects.select_related("invoice").iterator():
        user_id = li.invoice.user_id
        raw = (li.service_name or "").strip()
        if not raw:
            continue
        norm = normalize_for_match(raw)
        key = (user_id, norm)

        if key not in user_services:
            svc = Service.objects.create(
                user_id=user_id,
                canonical_name=raw,
                unit=li.unit,
            )
            user_services[key] = svc.id

        svc_id = user_services[key]
        if li.service_id != svc_id:
            li.service_id = svc_id
            li.save(update_fields=["service"])

        ServiceAlias.objects.get_or_create(
            service_id=svc_id,
            raw_name=raw,
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0005_service_servicealias_lineitem_service"),
    ]

    operations = [
        migrations.RunPython(populate_services, reverse_noop),
    ]

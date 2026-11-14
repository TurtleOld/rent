from django.db import migrations, models
from django.db.models import Count

# Дублирует models.NO_SERVICES_WARNING: миграция обязана быть самодостаточной.
NO_SERVICES_WARNING = "Не распознана ни одна услуга — квитанция исключена из графиков и итогов"


def mark_incomplete_without_services(apps, schema_editor):
    """Переводит старые «Обработан»-квитанции без услуг в «Обработан частично».

    PDF и распознанные суммы не трогаем: меняются только статус и warnings.
    """
    Invoice = apps.get_model("invoices", "Invoice")
    qs = (
        Invoice.objects.filter(status="processed")
        .annotate(items_count=Count("line_items"))
        .filter(items_count=0)
    )
    for invoice in qs:
        warnings = list(invoice.warnings or [])
        if NO_SERVICES_WARNING not in warnings:
            warnings.append(NO_SERVICES_WARNING)
        invoice.status = "incomplete"
        invoice.warnings = warnings
        invoice.save(update_fields=["status", "warnings", "updated_at"])


def restore_processed(apps, schema_editor):
    Invoice = apps.get_model("invoices", "Invoice")
    qs = (
        Invoice.objects.filter(status="incomplete")
        .annotate(items_count=Count("line_items"))
        .filter(items_count=0)
    )
    for invoice in qs:
        invoice.status = "processed"
        invoice.warnings = [
            w for w in (invoice.warnings or []) if w != NO_SERVICES_WARNING
        ]
        invoice.save(update_fields=["status", "warnings", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("invoices", "0011_lineitem_source_precision"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="status",
            field=models.CharField(
                choices=[
                    ("processing", "Обрабатывается"),
                    ("processed", "Обработан"),
                    ("incomplete", "Обработан частично"),
                    ("failed", "Ошибка"),
                ],
                default="processing",
                max_length=20,
            ),
        ),
        migrations.RunPython(mark_incomplete_without_services, restore_processed),
    ]

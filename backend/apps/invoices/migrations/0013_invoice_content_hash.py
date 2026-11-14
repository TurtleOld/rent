import hashlib
import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def fill_content_hash(apps, schema_editor):
    """Проставляет хэш существующим квитанциям, исторические дубли не трогает.

    Хэш получает только первая копия содержимого у пользователя; у поздних
    дублей остаётся NULL, который уникальный индекс не сравнивает. Записи
    и файлы дублей не удаляются. Квитанции без файла тоже остаются с NULL.
    """
    Invoice = apps.get_model("invoices", "Invoice")
    seen = set()
    for invoice in Invoice.objects.order_by("pk").iterator():
        if not invoice.pdf_file:
            continue
        try:
            with invoice.pdf_file.open("rb") as pdf:
                digest = hashlib.sha256(pdf.read()).hexdigest()
        except Exception:
            logger.warning("Не удалось прочитать PDF квитанции %s", invoice.pk)
            continue
        key = (invoice.user_id, digest)
        if key in seen:
            continue
        seen.add(key)
        invoice.content_hash = digest
        invoice.save(update_fields=["content_hash"])


class Migration(migrations.Migration):
    dependencies = [("invoices", "0012_invoice_incomplete_status")]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="content_hash",
            field=models.CharField(
                blank=True,
                help_text="SHA-256 содержимого PDF; защита от повторной загрузки",
                max_length=64,
                null=True,
            ),
        ),
        migrations.RunPython(fill_content_hash, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.UniqueConstraint(
                fields=("user", "content_hash"),
                name="uniq_user_invoice_content_hash",
            ),
        ),
    ]

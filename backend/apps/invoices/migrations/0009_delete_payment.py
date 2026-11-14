from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("invoices", "0008_invoice_manual_amount_due"),
    ]

    operations = [
        # Приложение payments удалено из INSTALLED_APPS, поэтому его миграции
        # больше не выполняются, а таблица остаётся в уже развёрнутых базах.
        migrations.RunSQL("DROP TABLE IF EXISTS payments_payment;"),
    ]

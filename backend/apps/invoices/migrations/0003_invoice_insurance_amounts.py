from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0002_lineitem_debt"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="amount_due_without_insurance",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Итого к оплате без учёта добровольного страхования",
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="amount_due_with_insurance",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Итого к оплате с учётом добровольного страхования",
                max_digits=10,
                null=True,
            ),
        ),
    ]

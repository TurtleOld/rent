from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="lineitem",
            name="debt",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Задолженность/переплата на начало периода",
                max_digits=10,
                null=True,
            ),
        ),
    ]

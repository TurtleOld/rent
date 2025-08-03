# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("epd_parser", "0004_servicecharge_recalculation"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecharge",
            name="unit",
            field=models.CharField(
                blank=True,
                help_text="Unit of measurement (кв.м., куб.м., кВт*ч, etc.)",
                max_length=20,
                verbose_name="Unit",
            ),
        ),
    ]

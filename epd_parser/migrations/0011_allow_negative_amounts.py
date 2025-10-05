"""Allow negative financial amounts for service and recalculation models."""

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    """Migration class for allowing negative financial amounts."""

    dependencies = [
        ("epd_parser", "0010_epddocument_epd_parser__created_ed11a8_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="servicecharge",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Calculated amount for this service",
                max_digits=10,
                verbose_name="Amount",
            ),
        ),
        migrations.AlterField(
            model_name="servicecharge",
            name="recalculation",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Recalculation amount",
                max_digits=10,
                verbose_name="Recalculation",
            ),
        ),
        migrations.AlterField(
            model_name="servicecharge",
            name="debt",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Previous debt amount",
                max_digits=10,
                verbose_name="Debt",
            ),
        ),
        migrations.AlterField(
            model_name="servicecharge",
            name="paid",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Amount already paid",
                max_digits=10,
                verbose_name="Paid",
            ),
        ),
        migrations.AlterField(
            model_name="servicecharge",
            name="total",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Total amount to pay (amount + debt - paid)",
                max_digits=10,
                verbose_name="Total",
            ),
        ),
        migrations.AlterField(
            model_name="recalculation",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Recalculation amount",
                max_digits=10,
                verbose_name="Amount",
            ),
        ),
    ]

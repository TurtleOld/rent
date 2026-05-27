import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0004_alter_lineitem_debt"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canonical_name", models.CharField(max_length=255)),
                ("unit", models.CharField(
                    blank=True,
                    help_text="Каноническая единица измерения (кв.м, куб.м, кВт·ч...).",
                    max_length=20,
                    null=True,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="services",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["canonical_name"],
            },
        ),
        migrations.AddField(
            model_name="lineitem",
            name="service",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="line_items",
                to="invoices.service",
            ),
        ),
        migrations.CreateModel(
            name="ServiceAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("raw_name", models.CharField(max_length=255)),
                ("service", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="aliases",
                    to="invoices.service",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="service",
            constraint=models.UniqueConstraint(
                fields=["user", "canonical_name"],
                name="uniq_user_service_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="servicealias",
            constraint=models.UniqueConstraint(
                fields=["service", "raw_name"],
                name="uniq_service_alias_raw",
            ),
        ),
    ]

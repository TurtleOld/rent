from decimal import Decimal

from django.conf import settings
from django.db import models


class Service(models.Model):
    """Канонический справочник услуг ЖКХ.

    Уникален в рамках пары (user, canonical_name) — у каждого
    пользователя свой каталог, потому что состав услуг и поставщики
    различаются.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="services",
    )
    canonical_name = models.CharField(max_length=255)
    unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Каноническая единица измерения (кв.м, куб.м, кВт·ч...).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "canonical_name"],
                name="uniq_user_service_canonical",
            ),
        ]
        ordering = ["canonical_name"]

    def __str__(self) -> str:
        return f"{self.canonical_name} ({self.user_id})"


class ServiceAlias(models.Model):
    """Связывает разные написания названия услуги из PDF с одной Service.

    Пример: «ХОЛОДНОЕ В/С», «ХОЛОДНОЕ ВОДОСНАБЖЕНИЕ», «ХВС» -> Service «ХВС».
    """

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    raw_name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "raw_name"],
                name="uniq_service_alias_raw",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.raw_name} -> {self.service.canonical_name}"


class Invoice(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Обрабатывается"
        PROCESSED = "processed", "Обработан"
        FAILED = "failed", "Ошибка"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    pdf_file = models.FileField(upload_to="invoices/")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    error_message = models.TextField(blank=True, null=True)
    raw_ai_response = models.JSONField(blank=True, null=True)

    # Extracted header fields (editable by user)
    provider_name = models.CharField(max_length=255, blank=True, null=True)
    account_number = models.CharField(max_length=255, blank=True, null=True)
    payer_name = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    # Period
    period_start = models.DateField(blank=True, null=True)
    period_end = models.DateField(blank=True, null=True)
    period_month = models.PositiveSmallIntegerField(blank=True, null=True)
    period_year = models.PositiveSmallIntegerField(blank=True, null=True)

    # Financial totals (editable by user)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    amount_charged = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    amount_paid_ai = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Оплачено согласно данным AI (не пользовательские платежи)",
    )
    amount_recalculation = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Итоговая сумма перерасчётов по счёту",
    )
    amount_due_without_insurance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Итого к оплате без учёта добровольного страхования",
    )
    amount_due_with_insurance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Итого к оплате с учётом добровольного страхования",
    )

    confidence = models.FloatField(blank=True, null=True)
    warnings = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invoice #{self.pk} — {self.provider_name or 'unknown'} ({self.status})"

    @property
    def payment_status(self) -> str:
        total_paid = sum(p.amount for p in self.payments.all())
        if total_paid == 0:
            return "unpaid"
        if self.amount_due and total_paid >= self.amount_due:
            return "paid"
        return "partially_paid"

    @property
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments.all()), Decimal("0"))


class LineItem(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    service_name = models.CharField(max_length=255)
    unit = models.CharField(max_length=50, blank=True, null=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    tariff = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    # amount_charged = начислено по тарифу (до перерасчёта)
    amount_charged = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # recalculation = сумма перерасчёта/доначисления (может отсутствовать в документе)
    recalculation = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # debt = задолженность/переплата на начало периода (может отсутствовать в документе)
    debt = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # amount = итого по строке
    amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    service = models.ForeignKey(
        "invoices.Service",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="line_items",
    )
    provider = models.CharField(max_length=255, blank=True, null=True)
    meter_id = models.CharField(max_length=100, blank=True, null=True)
    previous_reading = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    current_reading = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.service_name} — {self.amount}"

"""Django models for EPD (Unified Payment Document) data storage."""

from decimal import Decimal
from typing import Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

EPD_DOCUMENT_VERBOSE_NAME = "EPD Document"
SERVICE_NAME_VERBOSE_NAME = "Service Name"
SERVICE_NAME_HELP_TEXT = "Name of the utility service"


class EpdDocument(models.Model):
    """Main model for storing EPD document information."""

    # Personal information
    full_name: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_("Full Name"),
        help_text=_("Full name of the person responsible for payments"),
    )
    address: models.TextField = models.TextField(
        verbose_name=_("Address"),
        help_text=_("Full address of the property"),
    )
    account_number: models.CharField = models.CharField(
        max_length=50,
        verbose_name=_("Account Number"),
        help_text=_("Unique account number for the property"),
        db_index=True,
    )

    # Document metadata
    payment_period: models.CharField = models.CharField(
        max_length=20,
        verbose_name=_("Payment Period"),
        help_text=_('Payment period (e.g., "01.2024")'),
    )
    due_date: models.DateField = models.DateField(
        verbose_name=_("Due Date"),
        help_text=_("Payment due date"),
        null=True,
        blank=True,
    )

    # Financial totals
    total_without_insurance: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Total Without Insurance"),
        help_text=_("Total amount without insurance"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_with_insurance: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Total With Insurance"),
        help_text=_("Total amount including insurance"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    insurance_amount: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Insurance Amount"),
        help_text=_("Insurance amount"),
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("0.00"),
    )

    # Timestamps
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At"),
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At"),
    )

    class Meta:
        """Meta options for EpdDocument model."""

        verbose_name = _(EPD_DOCUMENT_VERBOSE_NAME)
        verbose_name_plural = _("EPD Documents")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_number"]),
            models.Index(fields=["payment_period"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["account_number", "created_at"]),
            models.Index(fields=["payment_period", "created_at"]),
        ]

    def __str__(self) -> str:
        """String representation of the model."""
        return f"{self.full_name} - {self.account_number} ({self.payment_period})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to calculate insurance amount."""
        if (
            self.total_with_insurance is not None
            and self.total_without_insurance is not None
        ):
            self.insurance_amount = (
                self.total_with_insurance - self.total_without_insurance
            )
        else:
            self.insurance_amount = Decimal("0.00")
        super().save(*args, **kwargs)


class ServiceCharge(models.Model):
    """Model for storing individual service charges from EPD."""

    document: models.ForeignKey[EpdDocument, EpdDocument] = models.ForeignKey(
        EpdDocument,
        on_delete=models.CASCADE,
        related_name="service_charges",
        verbose_name=_(EPD_DOCUMENT_VERBOSE_NAME),
    )

    # Service information
    service_name: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_(SERVICE_NAME_VERBOSE_NAME),
        help_text=_(SERVICE_NAME_HELP_TEXT),
    )

    # Volume and tariff
    volume: models.DecimalField = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name=_("Volume"),
        help_text=_("Volume of service consumed"),
        validators=[MinValueValidator(Decimal("0.0000"))],
        null=True,
        blank=True,
    )
    unit: models.CharField = models.CharField(
        max_length=20,
        verbose_name=_("Unit"),
        help_text=_("Unit of measurement (кв.м., куб.м., кВт*ч, etc.)"),
        blank=True,
    )
    tariff: models.DecimalField = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name=_("Tariff"),
        help_text=_("Tariff rate per unit"),
        validators=[MinValueValidator(Decimal("0.0000"))],
        null=True,
        blank=True,
    )

    # Financial amounts
    amount: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount"),
        help_text=_("Calculated amount for this service"),
    )
    recalculation: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Recalculation"),
        help_text=_("Recalculation amount"),
        default=Decimal("0.00"),
    )
    debt: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Debt"),
        help_text=_("Previous debt amount"),
        default=Decimal("0.00"),
    )
    paid: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Paid"),
        help_text=_("Amount already paid"),
        default=Decimal("0.00"),
    )
    total: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Total"),
        help_text=_("Total amount to pay (amount + debt - paid)"),
    )

    # Ordering
    order: models.PositiveIntegerField = models.PositiveIntegerField(
        verbose_name=_("Order"),
        help_text=_("Order of service in the document"),
        default=0,
    )

    class Meta:
        """Meta options for ServiceCharge model."""

        verbose_name = _("Service Charge")
        verbose_name_plural = _("Service Charges")
        ordering = ["document", "order"]
        indexes = [
            models.Index(fields=["document", "order"]),
            models.Index(fields=["service_name"]),
            models.Index(fields=["document", "service_name"]),
            models.Index(fields=["service_name", "total"]),
        ]

    def __str__(self) -> str:
        """String representation of the model."""
        return f"{self.document.account_number} - {self.service_name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to preserve original total from PDF."""
        # Не пересчитываем итого - используем данные из колонки "ИТОГО" напрямую
        # Это позволяет сохранить оригинальные значения из PDF, включая обнуление
        # отрицательных итого согласно правилам ЕПД
        super().save(*args, **kwargs)


class MeterReading(models.Model):
    """Model for storing meter readings from EPD."""

    document: models.ForeignKey[EpdDocument, EpdDocument] = models.ForeignKey(
        EpdDocument,
        on_delete=models.CASCADE,
        related_name="meter_readings",
        verbose_name=_(EPD_DOCUMENT_VERBOSE_NAME),
    )

    # Meter information
    service_name: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_(SERVICE_NAME_VERBOSE_NAME),
        help_text=_(SERVICE_NAME_HELP_TEXT),
    )
    meter_type: models.CharField = models.CharField(
        max_length=50,
        verbose_name=_("Meter Type"),
        help_text=_("Type of meter (ИПУ, ОДПУ, etc.)"),
        blank=True,
    )
    meter_number: models.CharField = models.CharField(
        max_length=50,
        verbose_name=_("Meter Number"),
        help_text=_("Meter serial number"),
        blank=True,
    )
    verification_date: models.DateField = models.DateField(
        verbose_name=_("Verification Date"),
        help_text=_("Date of meter verification"),
        null=True,
        blank=True,
    )

    # Readings
    previous_reading: models.DecimalField = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name=_("Previous Reading"),
        help_text=_("Previous meter reading"),
        validators=[MinValueValidator(Decimal("0.0000"))],
        null=True,
        blank=True,
    )
    current_reading: models.DecimalField = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name=_("Current Reading"),
        help_text=_("Current meter reading"),
        validators=[MinValueValidator(Decimal("0.0000"))],
        null=True,
        blank=True,
    )

    # Ordering
    order: models.PositiveIntegerField = models.PositiveIntegerField(
        verbose_name=_("Order"),
        help_text=_("Display order"),
        default=0,
    )

    class Meta:
        """Meta options for MeterReading model."""

        verbose_name = _("Meter Reading")
        verbose_name_plural = _("Meter Readings")
        ordering = ["document", "order"]
        indexes = [
            models.Index(fields=["document", "service_name"]),
            models.Index(fields=["document", "order"]),
            models.Index(fields=["service_name", "meter_number"]),
        ]

    def __str__(self) -> str:
        """String representation of the model."""
        return f"{self.service_name} - {self.meter_number} ({self.document})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the meter reading."""
        if not self.order:
            last_order = MeterReading.objects.filter(document=self.document).aggregate(
                models.Max("order")
            )["order__max"]
            self.order = (last_order or 0) + 1
        super().save(*args, **kwargs)


class Recalculation(models.Model):
    """Model for storing recalculation information from EPD."""

    document: models.ForeignKey[EpdDocument, EpdDocument] = models.ForeignKey(
        EpdDocument,
        on_delete=models.CASCADE,
        related_name="recalculations",
        verbose_name=_(EPD_DOCUMENT_VERBOSE_NAME),
    )

    # Recalculation information
    service_name: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_(SERVICE_NAME_VERBOSE_NAME),
        help_text=_(SERVICE_NAME_HELP_TEXT),
    )
    reason: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_("Reason"),
        help_text=_("Reason for recalculation"),
        blank=True,
    )
    amount: models.DecimalField = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount"),
        help_text=_("Recalculation amount"),
    )

    # Ordering
    order: models.PositiveIntegerField = models.PositiveIntegerField(
        verbose_name=_("Order"),
        help_text=_("Display order"),
        default=0,
    )

    class Meta:
        """Meta options for Recalculation model."""

        verbose_name = _("Recalculation")
        verbose_name_plural = _("Recalculations")
        ordering = ["document", "order"]
        indexes = [
            models.Index(fields=["document", "service_name"]),
            models.Index(fields=["document", "order"]),
            models.Index(fields=["service_name", "amount"]),
        ]

    def __str__(self) -> str:
        """String representation of the model."""
        return f"{self.service_name} - {self.amount} ({self.document})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the recalculation."""
        if not self.order:
            last_order = Recalculation.objects.filter(document=self.document).aggregate(
                models.Max("order")
            )["order__max"]
            self.order = (last_order or 0) + 1
        super().save(*args, **kwargs)

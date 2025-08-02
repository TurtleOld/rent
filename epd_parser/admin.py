"""Django admin configuration for EPD parser application."""

from decimal import Decimal
from typing import Any

from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import EpdDocument, ServiceCharge, MeterReading, Recalculation


@admin.register(ServiceCharge)
class ServiceChargeAdmin(admin.ModelAdmin):
    """Admin interface for ServiceCharge model."""

    list_display = [
        "document",
        "service_name",
        "volume",
        "tariff",
        "amount",
        "debt",
        "paid",
        "total",
        "order",
    ]
    list_filter = ["service_name", "document__payment_period"]
    search_fields = ["service_name", "document__full_name", "document__account_number"]
    ordering = ["document", "order"]
    readonly_fields = ["total"]

    fieldsets = (
        (
            _("Document"),
            {
                "fields": ["document"],
            },
        ),
        (
            _("Service Information"),
            {
                "fields": ["service_name", "order"],
            },
        ),
        (
            _("Volume and Tariff"),
            {
                "fields": ["volume", "tariff"],
            },
        ),
        (
            _("Financial Information"),
            {
                "fields": ["amount", "debt", "paid", "total"],
            },
        ),
    )


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    """Admin interface for MeterReading model."""

    list_display = [
        "document",
        "service_name",
        "meter_type",
        "meter_number",
        "verification_date",
        "previous_reading",
        "current_reading",
        "order",
    ]
    list_filter = ["meter_type", "service_name", "document__payment_period"]
    search_fields = ["service_name", "meter_number", "document__full_name"]
    ordering = ["document", "order"]

    fieldsets = (
        (
            _("Document"),
            {
                "fields": ["document"],
            },
        ),
        (
            _("Service Information"),
            {
                "fields": ["service_name", "order"],
            },
        ),
        (
            _("Meter Information"),
            {
                "fields": ["meter_type", "meter_number", "verification_date"],
            },
        ),
        (
            _("Readings"),
            {
                "fields": ["previous_reading", "current_reading"],
            },
        ),
    )


@admin.register(Recalculation)
class RecalculationAdmin(admin.ModelAdmin):
    """Admin interface for Recalculation model."""

    list_display = [
        "document",
        "service_name",
        "reason",
        "amount",
        "order",
    ]
    list_filter = ["service_name", "document__payment_period"]
    search_fields = ["service_name", "reason", "document__full_name"]
    ordering = ["document", "order"]

    fieldsets = (
        (
            _("Document"),
            {
                "fields": ["document"],
            },
        ),
        (
            _("Recalculation Information"),
            {
                "fields": ["service_name", "reason", "amount", "order"],
            },
        ),
    )


@admin.register(EpdDocument)
class EpdDocumentAdmin(admin.ModelAdmin):
    """Admin interface for EpdDocument model."""

    list_display = [
        "full_name",
        "account_number",
        "payment_period",
        "due_date",
        "total_without_insurance",
        "total_with_insurance",
        "insurance_amount",
        "created_at",
        "pdf_file_link",
    ]
    list_filter = [
        "payment_period",
        "due_date",
        "created_at",
    ]
    search_fields = [
        "full_name",
        "account_number",
        "address",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "insurance_amount",
    ]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            _("Personal Information"),
            {
                "fields": ["full_name", "address", "account_number"],
            },
        ),
        (
            _("Document Information"),
            {
                "fields": ["payment_period", "due_date"],
            },
        ),
        (
            _("Financial Information"),
            {
                "fields": [
                    "total_without_insurance",
                    "total_with_insurance",
                    "insurance_amount",
                ],
            },
        ),
        (
            _("File Information"),
            {
                "fields": ["pdf_file"],
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    )

    def pdf_file_link(self, obj):
        """Display PDF file as a link."""
        if obj.pdf_file:
            return format_html(
                '<a href="{}" target="_blank">View PDF</a>',
                obj.pdf_file.url,
            )
        return _("No file")

    pdf_file_link.short_description = _("PDF File")

    def get_queryset(self, request):
        """Optimize queryset with related data."""
        return super().get_queryset(request).select_related()

    def save_model(self, request, obj, form, change):
        """Calculate insurance amount on save."""
        if obj.total_with_insurance and obj.total_without_insurance:
            obj.insurance_amount = (
                obj.total_with_insurance - obj.total_without_insurance
            )
        super().save_model(request, obj, form, change)


# Customize admin site
admin.site.site_header = _("EPD Parser Administration")
admin.site.site_title = _("EPD Parser Admin")
admin.site.index_title = _("Welcome to EPD Parser Administration")

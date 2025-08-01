"""Django admin configuration for EPD parser application."""

from decimal import Decimal
from typing import Any

from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import EpdDocument, ServiceCharge


@admin.register(ServiceCharge)
class ServiceChargeAdmin(admin.ModelAdmin):
    """Admin configuration for ServiceCharge model."""
    
    list_display = [
        'service_name',
        'document_link',
        'volume',
        'tariff',
        'amount',
        'debt',
        'paid',
        'total',
        'order',
    ]
    list_filter = [
        'service_name',
        'document__payment_period',
        'document__account_number',
    ]
    search_fields = [
        'service_name',
        'document__full_name',
        'document__account_number',
    ]
    readonly_fields = ['total']
    ordering = ['document', 'order']
    
    def document_link(self, obj: ServiceCharge) -> str:
        """Create a link to the related document."""
        if obj.document:
            return format_html(
                '<a href="{}">{}</a>',
                f'/admin/epd_parser/epddocument/{obj.document.pk}/change/',
                obj.document.account_number
            )
        return '-'
    document_link.short_description = _('Document')
    document_link.admin_order_field = 'document__account_number'


class ServiceChargeInline(admin.TabularInline):
    """Inline admin for ServiceCharge model."""
    
    model = ServiceCharge
    extra = 0
    readonly_fields = ['total']
    fields = [
        'service_name',
        'volume',
        'tariff',
        'amount',
        'debt',
        'paid',
        'total',
        'order',
    ]
    ordering = ['order']


@admin.register(EpdDocument)
class EpdDocumentAdmin(admin.ModelAdmin):
    """Admin configuration for EpdDocument model."""
    
    list_display = [
        'account_number',
        'full_name',
        'payment_period',
        'due_date',
        'total_without_insurance',
        'total_with_insurance',
        'insurance_amount',
        'service_charges_count',
        'created_at',
    ]
    list_filter = [
        'payment_period',
        'due_date',
        'created_at',
    ]
    search_fields = [
        'full_name',
        'address',
        'account_number',
        'payment_period',
    ]
    readonly_fields = [
        'insurance_amount',
        'created_at',
        'updated_at',
        'pdf_file_link',
    ]
    inlines = [ServiceChargeInline]
    ordering = ['-created_at']
    
    fieldsets = (
        (_('Personal Information'), {
            'fields': ('full_name', 'address', 'account_number')
        }),
        (_('Payment Information'), {
            'fields': ('payment_period', 'due_date')
        }),
        (_('Financial Information'), {
            'fields': (
                'total_without_insurance',
                'total_with_insurance',
                'insurance_amount'
            )
        }),
        (_('File Information'), {
            'fields': ('pdf_file', 'pdf_file_link')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def service_charges_count(self, obj: EpdDocument) -> int:
        """Display count of service charges."""
        return obj.service_charges.count()
    service_charges_count.short_description = _('Services')
    service_charges_count.admin_order_field = 'service_charges__count'
    
    def pdf_file_link(self, obj: EpdDocument) -> str:
        """Create a link to download the PDF file."""
        if obj.pdf_file:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.pdf_file.url,
                _('Download PDF')
            )
        return _('No file')
    pdf_file_link.short_description = _('PDF File')
    
    def get_queryset(self, request: Any) -> Any:
        """Optimize queryset with related data."""
        return super().get_queryset(request).prefetch_related('service_charges')
    
    def get_readonly_fields(self, request: Any, obj: Any = None) -> tuple[str, ...]:
        """Make insurance_amount readonly."""
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if 'insurance_amount' not in readonly_fields:
            readonly_fields.append('insurance_amount')
        return tuple(readonly_fields)
    
    def save_model(self, request: Any, obj: EpdDocument, form: Any, change: Any) -> None:
        """Override save to calculate insurance amount."""
        if obj.total_with_insurance and obj.total_without_insurance:
            obj.insurance_amount = obj.total_with_insurance - obj.total_without_insurance
        super().save_model(request, obj, form, change)


# Customize admin site
admin.site.site_header = _('EPD Parser Administration')
admin.site.site_title = _('EPD Parser Admin')
admin.site.index_title = _('Welcome to EPD Parser Administration') 
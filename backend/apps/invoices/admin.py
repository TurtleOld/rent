from django.contrib import admin

from .models import Invoice, LineItem


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    readonly_fields = (
        "service_name", "unit", "quantity", "tariff",
        "amount_charged", "recalculation", "amount",
        "meter_id", "previous_reading", "current_reading",
    )


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "provider_name", "status", "amount_due", "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "raw_ai_response", "confidence", "warnings", "created_at", "updated_at")
    inlines = [LineItemInline]

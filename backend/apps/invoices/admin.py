from django.contrib import admin
from django.db import transaction

from .models import Invoice, LineItem, Service, ServiceAlias


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


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("id", "canonical_name", "user", "unit", "aliases_count")
    list_filter = ("user",)
    search_fields = ("canonical_name", "aliases__raw_name")
    actions = ["merge_into_first"]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("aliases")

    @admin.display(description="Алиасов")
    def aliases_count(self, obj: Service) -> int:
        return obj.aliases.count()

    @admin.action(description="Объединить выбранные в первую запись")
    def merge_into_first(self, request, queryset) -> None:
        """Перепривязывает LineItem и ServiceAlias всех дублей к первому Service.

        Пропускает сервисы другого пользователя. Удаляет источники после слияния.
        Всё выполняется в одной транзакции.
        """
        services = list(queryset.order_by("id"))
        if len(services) < 2:
            self.message_user(request, "Нужно выбрать минимум 2 сервиса.")
            return

        target = services[0]
        merged = 0
        skipped = 0

        with transaction.atomic():
            for src in services[1:]:
                if src.user_id != target.user_id:
                    skipped += 1
                    continue
                LineItem.objects.filter(service=src).update(service=target)
                for alias in ServiceAlias.objects.filter(service=src):
                    ServiceAlias.objects.get_or_create(service=target, raw_name=alias.raw_name)
                src.delete()
                merged += 1

        msg = f"Объединено {merged} сервис(ов) в Service #{target.id} «{target.canonical_name}»."
        if skipped:
            msg += f" Пропущено {skipped} (другой пользователь)."
        self.message_user(request, msg)

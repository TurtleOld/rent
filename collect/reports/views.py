from datetime import timedelta, datetime

from django.views.generic import TemplateView

from collect.rent.models import ServiceInfo


class ReportsView(TemplateView):
    template_name = 'reports/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)

        # Получаем список всех предыдущих месяцев за последний год
        all_previous_months = []
        for _ in range(1, 13):
            # Вычисляем первый день текущего месяца
            current_month_start = first_day_of_month - timedelta(
                days=first_day_of_month.day - 1
            )
            # Вычисляем первый день предыдущего месяца
            previous_month_start = current_month_start - timedelta(days=1)
            # Добавляем предыдущий месяц в список
            all_previous_months.append(previous_month_start)
            # Обновляем текущий месяц для следующей итерации
            first_day_of_month = previous_month_start

        # Создаем словарь для хранения изменений по каждому месяцу
        all_monthly_changes = {}

        # Проходимся по каждому предыдущему месяцу
        for previous_month in all_previous_months:
            # Получаем первый день текущего месяца и первый день предыдущего месяца
            current_month_start = previous_month + timedelta(days=1)
            previous_month_start = previous_month

            # Фильтруем объекты ServiceInfo для текущего и предыдущего месяца
            current_month_services = ServiceInfo.objects.filter(
                date__year=current_month_start.year,
                date__month=current_month_start.month,
            )
            previous_month_services = ServiceInfo.objects.filter(
                date__year=previous_month_start.year,
                date__month=previous_month_start.month,
            )

            # Выполняем вычисления для определения изменений в тарифах и других параметрах
            monthly_changes = {}
            for service in current_month_services:
                previous_service = previous_month_services.filter(
                    type_service=service.type_service
                ).first()
                if previous_service:
                    change = {
                        'previous_tariff': previous_service.tariff,
                        'tariff_change': service.tariff - previous_service.tariff,
                        'current_tariff': service.tariff,
                        'previous_scope_service': previous_service.scope_service,
                        'scope_service': service.scope_service
                        - previous_service.scope_service,
                        'current_scope_service': service.scope_service,
                        'units': service.units,
                        'accrued_service': service.accrued_tariff
                        - previous_service.accrued_tariff,
                        'previous_accrued_service': previous_service.accrued_tariff,
                        'current_accrued_service': service.accrued_tariff,
                        'previous_recalculations': previous_service.recalculations,
                        'recalculations': service.recalculations
                        - previous_service.recalculations,
                        'current_recalculations': service.recalculations,
                        'previous_total_change': previous_service.total,
                        'total_change': service.total - previous_service.total,
                        'current_total_change': service.total,
                    }
                    monthly_changes[service.type_service] = change

            # Сохраняем изменения для текущего месяца в словаре
            all_monthly_changes[current_month_start] = monthly_changes
        context['all_monthly_changes'] = all_monthly_changes

        return context

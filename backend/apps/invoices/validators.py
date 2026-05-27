"""Валидаторы консистентности инвойса.

Все проверки — soft: возвращают список текстовых warning'ов,
ничего не блокируют. PDF может содержать ошибки поставщика —
наша задача показать их пользователю, а не исправлять.
"""
from decimal import Decimal
from typing import Iterable

from .models import Invoice, LineItem

TOLERANCE = Decimal("0.02")


def _close(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= TOLERANCE


def check_line_item(li: LineItem) -> list[str]:
    """Проверяет арифметику одной строки услуги.

    Args:
        li: Строка услуги для проверки.

    Returns:
        Список текстовых предупреждений (пустой, если ошибок нет).
    """
    warnings: list[str] = []

    if li.quantity is not None and li.tariff is not None and li.amount_charged is not None:
        expected = (li.quantity * li.tariff).quantize(Decimal("0.01"))
        if not _close(expected, li.amount_charged):
            warnings.append(
                f"«{li.service_name}»: количество × тариф"
                f" ({expected}) ≠ начислено ({li.amount_charged})."
            )

    if li.amount_charged is not None and li.amount is not None:
        rec = li.recalculation or Decimal("0")
        debt = li.debt or Decimal("0")
        expected_total = (li.amount_charged + rec + debt).quantize(Decimal("0.01"))
        if not _close(expected_total, li.amount):
            warnings.append(
                f"«{li.service_name}»: начислено + перерасчёт + долг"
                f" ({expected_total}) ≠ итого ({li.amount})."
            )

    return warnings


def check_invoice_totals(invoice: Invoice, line_items: Iterable[LineItem]) -> list[str]:
    """Проверяет соответствие суммы строк итогу квитанции.

    Args:
        invoice: Инвойс с полем amount_due / amount_due_without_insurance.
        line_items: Строки услуг инвойса.

    Returns:
        Список текстовых предупреждений (пустой, если ошибок нет).
    """
    total = sum((li.amount or Decimal("0") for li in line_items), Decimal("0"))
    reference = invoice.amount_due_without_insurance or invoice.amount_due
    if reference is not None and not _close(total, reference):
        return [
            f"Сумма по строкам ({total}) ≠ итог квитанции ({reference})."
        ]
    return []


def run_all_checks(invoice: Invoice, line_items: Iterable[LineItem]) -> list[str]:
    """Запускает все проверки консистентности.

    Args:
        invoice: Инвойс.
        line_items: Строки услуг инвойса.

    Returns:
        Объединённый список предупреждений от всех проверок.
    """
    items = list(line_items)
    out: list[str] = []
    for li in items:
        out.extend(check_line_item(li))
    out.extend(check_invoice_totals(invoice, items))
    return out

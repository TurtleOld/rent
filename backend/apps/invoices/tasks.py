import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction

from .models import Invoice, LineItem, Service, ServiceAlias
from .pdf_parser import parse_epd
from .units import normalize_unit
from .validators import run_all_checks


def _json_serializable(obj: dict) -> dict:
    """Рекурсивно конвертирует Decimal → str для сохранения в JSON-поле."""
    return json.loads(json.dumps(obj, default=str))

logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        logger.warning("Could not parse date: %s", value)
        return None


def _to_decimal(value, decimal_places: int = 2) -> Decimal | None:
    if value is None:
        return None
    try:
        return round(Decimal(str(value)), decimal_places)
    except (InvalidOperation, ValueError):
        return None


@shared_task(
    name="invoices.process_invoice",
    soft_time_limit=60,
    time_limit=120,
)
def process_invoice(invoice_id: int) -> None:
    try:
        invoice = Invoice.objects.get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Invoice %s not found, skipping", invoice_id)
        return

    if invoice.status != Invoice.Status.PROCESSING:
        logger.info("Invoice %s already in status %s, skipping", invoice_id, invoice.status)
        return

    # Ошибки разбора PDF не временные: повторять бесполезно, есть кнопка «Перепарсить».
    try:
        _do_process(invoice)
    except Exception as exc:
        logger.exception("Unhandled error processing invoice %s", invoice_id)
        _fail(invoice, f"Ошибка обработки: {exc}")


def _do_process(invoice: Invoice) -> None:
    try:
        invoice.pdf_file.seek(0)
        parsed_data = parse_epd(invoice.pdf_file)
    except SoftTimeLimitExceeded:
        _fail(invoice, "PDF слишком большой или повреждён.")
        return
    except Exception as exc:
        logger.exception("PDF parsing failed for invoice %s", invoice.pk)
        _fail(invoice, f"Ошибка парсинга PDF: {exc}")
        return

    period = parsed_data.get("period") or {}
    totals = parsed_data.get("totals") or {}

    invoice.raw_ai_response = _json_serializable(parsed_data)
    invoice.provider_name = parsed_data.get("provider_name")
    invoice.account_number = parsed_data.get("account_number")
    invoice.payer_name = parsed_data.get("payer_name")
    invoice.address = parsed_data.get("address")
    invoice.period_start = _parse_date(period.get("start_date"))
    invoice.period_end = _parse_date(period.get("end_date"))
    invoice.period_month = period.get("month")
    invoice.period_year = period.get("year")
    invoice.amount_due = _to_decimal(totals.get("amount_due"))
    invoice.amount_due_without_insurance = _to_decimal(totals.get("amount_due_without_insurance"))
    invoice.amount_due_with_insurance = _to_decimal(totals.get("amount_due_with_insurance"))
    invoice.amount_charged = _to_decimal(totals.get("amount_charged"))
    invoice.amount_paid_ai = _to_decimal(totals.get("amount_paid"))
    invoice.amount_recalculation = _to_decimal(totals.get("amount_recalculation"))
    invoice.confidence = parsed_data.get("confidence")
    invoice.warnings = parsed_data.get("warnings") or []
    invoice.status = Invoice.Status.PROCESSED
    invoice.error_message = None

    line_items_data = parsed_data.get("line_items") or []
    unit_warnings: list[str] = []
    line_items = []
    for item in line_items_data:
        raw_name = item.get("service_name", "")
        if not raw_name:
            continue
        raw_unit = item.get("unit")
        normalized = normalize_unit(raw_unit)
        if raw_unit and normalized is None:
            unit_warnings.append(f"Неизвестная единица «{raw_unit}» у «{raw_name}».")
        unit = normalized or raw_unit
        line_items.append(LineItem(
            invoice=invoice,
            service_name=raw_name,
            unit=unit,
            quantity=_to_decimal(item.get("quantity"), 6),
            tariff=_to_decimal(item.get("tariff"), 4),
            amount_charged=_to_decimal(item.get("amount_charged")),
            recalculation=_to_decimal(item.get("recalculation")),
            debt=_to_decimal(item.get("debt")),
            amount=_to_decimal(item.get("amount")),
            provider=item.get("provider"),
            meter_id=item.get("meter_id"),
            previous_reading=_to_decimal(item.get("previous_reading"), 4),
            current_reading=_to_decimal(item.get("current_reading"), 4),
        ))

    if unit_warnings:
        invoice.warnings = (invoice.warnings or []) + unit_warnings

    with transaction.atomic():
        invoice.save()
        LineItem.objects.filter(invoice=invoice).delete()
        saved_items = LineItem.objects.bulk_create(line_items)

        for li in saved_items:
            li.service = _resolve_service(invoice.user_id, li.service_name, li.unit)
        LineItem.objects.bulk_update(saved_items, ["service"])

        extra_warnings = run_all_checks(invoice, saved_items)
        if extra_warnings:
            invoice.warnings = (invoice.warnings or []) + extra_warnings
            invoice.save(update_fields=["warnings", "updated_at"])

    logger.info(
        "Invoice %s processed successfully. %d line items saved.",
        invoice.pk,
        len(line_items),
    )


def _resolve_service(user_id: int, raw_name: str, normalized_unit: str | None) -> Service:
    """Находит или создаёт Service для данного пользователя и raw_name.

    Args:
        user_id: ID пользователя.
        raw_name: Сырое название услуги из PDF.
        normalized_unit: Нормализованная единица измерения.

    Returns:
        Существующий или только что созданный Service.
    """
    alias = (
        ServiceAlias.objects
        .select_related("service")
        .filter(service__user_id=user_id, raw_name=raw_name)
        .first()
    )
    if alias:
        return alias.service

    service, created = Service.objects.get_or_create(
        user_id=user_id,
        canonical_name=raw_name,
        defaults={"unit": normalized_unit},
    )
    ServiceAlias.objects.get_or_create(service=service, raw_name=raw_name)
    return service


def _fail(invoice: Invoice, message: str) -> None:
    invoice.status = Invoice.Status.FAILED
    invoice.error_message = message
    invoice.save(update_fields=["status", "error_message", "updated_at"])

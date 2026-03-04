import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from celery import shared_task

from .models import Invoice, LineItem
from .pdf_parser import parse_epd


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


def _validate_parsed_data(data: dict) -> list[str]:
    """Валидация структуры распарсенных данных."""
    errors: list[str] = []
    if data.get("document_type") != "utility_bill":
        errors.append("document_type должен быть 'utility_bill'")
    if not isinstance(data.get("line_items"), list):
        errors.append("line_items должен быть массивом")
    confidence = data.get("confidence")
    if confidence is not None:
        try:
            if not (0 <= float(confidence) <= 1):
                errors.append("confidence должен быть от 0 до 1")
        except (TypeError, ValueError):
            errors.append(f"confidence невалидное значение: {confidence}")
    period = data.get("period") or {}
    for date_field in ("start_date", "end_date"):
        val = period.get(date_field)
        if val is not None:
            try:
                date.fromisoformat(val)
            except (ValueError, TypeError):
                errors.append(f"period.{date_field} — невалидная дата: {val}")
    return errors


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="invoices.process_invoice",
)
def process_invoice(self, invoice_id: int) -> None:
    try:
        invoice = Invoice.objects.get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Invoice %s not found, skipping", invoice_id)
        return

    if invoice.status != Invoice.Status.PROCESSING:
        logger.info("Invoice %s already in status %s, skipping", invoice_id, invoice.status)
        return

    try:
        _do_process(invoice)
    except Exception as exc:
        logger.exception("Unhandled error processing invoice %s", invoice_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            invoice.status = Invoice.Status.FAILED
            invoice.error_message = f"Превышено количество попыток: {exc}"
            invoice.save(update_fields=["status", "error_message", "updated_at"])


def _do_process(invoice: Invoice) -> None:
    try:
        invoice.pdf_file.seek(0)
    except Exception as exc:
        _fail(invoice, f"Не удалось прочитать PDF: {exc}")
        raise

    try:
        parsed_data = parse_epd(invoice.pdf_file)
    except Exception as exc:
        msg = f"Ошибка парсинга PDF: {exc}"
        logger.exception(msg)
        _fail(invoice, msg)
        raise

    errors = _validate_parsed_data(parsed_data)
    if errors:
        msg = "Валидация не пройдена: " + "; ".join(errors)
        invoice.raw_ai_response = parsed_data
        _fail(invoice, msg, raw=parsed_data)
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
    invoice.save()

    LineItem.objects.filter(invoice=invoice).delete()
    line_items_data = parsed_data.get("line_items") or []
    line_items = [
        LineItem(
            invoice=invoice,
            service_name=item.get("service_name", ""),
            unit=item.get("unit"),
            quantity=_to_decimal(item.get("quantity"), 4),
            tariff=_to_decimal(item.get("tariff"), 4),
            amount_charged=_to_decimal(item.get("amount_charged")),
            recalculation=_to_decimal(item.get("recalculation")),
            debt=_to_decimal(item.get("debt")),
            amount=_to_decimal(item.get("amount")),
            provider=item.get("provider"),
            meter_id=item.get("meter_id"),
            previous_reading=_to_decimal(item.get("previous_reading"), 4),
            current_reading=_to_decimal(item.get("current_reading"), 4),
        )
        for item in line_items_data
        if item.get("service_name")
    ]
    LineItem.objects.bulk_create(line_items)

    logger.info(
        "Invoice %s processed successfully. %d line items saved.",
        invoice.pk,
        len(line_items),
    )


def _fail(invoice: Invoice, message: str, raw: dict | None = None) -> None:
    invoice.status = Invoice.Status.FAILED
    invoice.error_message = message
    if raw is not None:
        invoice.raw_ai_response = raw
    fields = ["status", "error_message", "updated_at"]
    if raw is not None:
        fields.append("raw_ai_response")
    invoice.save(update_fields=fields)

import base64
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from celery import shared_task
from django.conf import settings

from .models import Invoice, LineItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты парсер российских квитанций ЖКХ (единый платёжный документ).
Извлеки все структурированные данные из предоставленного PDF и верни ТОЛЬКО JSON-объект
без markdown-разметки, без пояснений, без лишнего текста.

Строгая схема ответа:
{
  "document_type": "utility_bill",
  "provider_name": строка или null,
  "account_number": строка или null,
  "payer_name": строка или null,
  "address": строка или null,
  "period": {
    "start_date": "YYYY-MM-DD" или null,
    "end_date": "YYYY-MM-DD" или null,
    "month": целое 1-12 или null,
    "year": целое или null
  },
  "totals": {
    "amount_due": число или null,
    "amount_due_without_insurance": число или null,
    "amount_due_with_insurance": число или null,
    "amount_charged": число или null,
    "amount_paid": число или null,
    "amount_recalculation": число или null,
    "currency": "RUB"
  },
  "line_items": [
    {
      "service_name": строка,
      "unit": строка или null,
      "quantity": число или null,
      "tariff": число или null,
      "amount_charged": число или null,
      "recalculation": число или null,
      "debt": число или null,
      "amount": число или null,
      "provider": строка или null,
      "meter_id": строка или null,
      "previous_reading": число или null,
      "current_reading": число или null
    }
  ],
  "confidence": число от 0 до 1,
  "warnings": [строка]
}

Правила:
- Никогда не выдумывай значения. Если значение отсутствует или неясно — ставь null и добавляй предупреждение в warnings.
- Сохраняй оригинальный русский текст названий услуг как есть.
- line_items всегда массив (пустой если ничего не найдено).
- Все числа — только цифры без пробелов и символов валюты.
- Даты строго в формате YYYY-MM-DD.
- Валюта всегда "RUB".
- amount_due_without_insurance — итоговая сумма к оплате БЕЗ учёта добровольного страхования (строка "Итого к оплате за ... без учёта добровольного страхования"), иначе null.
- amount_due_with_insurance — итоговая сумма к оплате С учётом добровольного страхования (строка "Итого к оплате за ... с учётом добровольного страхования"), иначе null.
- amount_due — использовать значение amount_due_without_insurance если оно присутствует, иначе общую итоговую сумму к оплате.
- recalculation — значение из колонки "Перерасчёты" если она присутствует в документе, иначе null.
- debt — значение из колонки "Задолженность/Переплата на начало периода" (переплата может быть отрицательным числом), если колонка присутствует в документе, иначе null.
- amount_charged — значение из колонки "Начислено по тарифу".
- amount — итоговое значение по строке (колонка "ИТОГО").
"""


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


def _validate_ai_response(data: dict) -> list[str]:
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
    totals = data.get("totals") or {}
    if totals.get("currency") and totals["currency"] != "RUB":
        errors.append(f"Недопустимая валюта: {totals['currency']}. Ожидается RUB.")
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
        pdf_bytes = invoice.pdf_file.read()
    except Exception as exc:
        _fail(invoice, f"Не удалось прочитать PDF: {exc}")
        raise

    try:
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()
        payload = {
            "model": settings.AI_API_MODEL,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Извлеки данные из этой квитанции ЖКХ согласно схеме.",
                        },
                    ],
                }
            ],
        }
        response = httpx.post(
            settings.AI_API_URL,
            headers={
                "Authorization": f"Bearer {settings.AI_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.AI_API_TIMEOUT,
        )
        response.raise_for_status()
        raw_response = response.json()
        ai_text = raw_response["content"][0]["text"].strip()
        if ai_text.startswith("```"):
            ai_text = ai_text.split("\n", 1)[-1]
            ai_text = ai_text.rsplit("```", 1)[0].strip()
        ai_data: dict = json.loads(ai_text)
    except httpx.HTTPStatusError as exc:
        msg = f"AI API вернул {exc.response.status_code}: {exc.response.text[:500]}"
        logger.error(msg)
        _fail(invoice, msg)
        raise
    except httpx.RequestError as exc:
        msg = f"Ошибка запроса к AI API: {exc}"
        logger.error(msg)
        _fail(invoice, msg)
        raise
    except Exception as exc:
        msg = f"Невалидный JSON от AI API: {exc}"
        logger.error(msg)
        _fail(invoice, msg)
        raise

    errors = _validate_ai_response(ai_data)
    if errors:
        msg = "Валидация ответа AI не пройдена: " + "; ".join(errors)
        invoice.raw_ai_response = ai_data
        _fail(invoice, msg, raw=ai_data)
        return

    period = ai_data.get("period") or {}
    totals = ai_data.get("totals") or {}

    invoice.raw_ai_response = ai_data
    invoice.provider_name = ai_data.get("provider_name")
    invoice.account_number = ai_data.get("account_number")
    invoice.payer_name = ai_data.get("payer_name")
    invoice.address = ai_data.get("address")
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
    invoice.confidence = ai_data.get("confidence")
    invoice.warnings = ai_data.get("warnings") or []
    invoice.status = Invoice.Status.PROCESSED
    invoice.error_message = None
    invoice.save()

    LineItem.objects.filter(invoice=invoice).delete()
    line_items_data = ai_data.get("line_items") or []
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

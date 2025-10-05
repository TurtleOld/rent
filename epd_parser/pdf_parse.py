"""PDF parsing module for EPD documents."""

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pdfplumber
from pdf2docx import Converter

from .models import EpdDocument, Recalculation, ServiceCharge

logger = logging.getLogger(__name__)


@dataclass
class AmountFragment:
    """Container describing a parsed numeric fragment."""

    magnitude: Decimal
    signed: Decimal
    segment_lower: str
    has_explicit_sign: bool


_DECIMAL_PATTERN = re.compile(
    r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?",
    re.UNICODE,
)

_COLUMN_SIGN_HINTS: dict[str, dict[str, Any]] = {
    "recalculation": {
        "positive": ("начис", "доначис", "увелич", "поступ"),
        "negative": ("уменьш", "переплат", "сниж", "вычет"),
        "alternate": True,
    },
    "debt": {
        "positive": ("задолж", "долг"),
        "negative": ("переплат", "аванс"),
        "alternate": True,
    },
    "paid": {
        "positive": (),
        "negative": ("переплат",),
        "alternate": False,
    },
}


def _prepare_amount_text(amount_str: Any) -> tuple[str, list[str], str]:
    """Normalise amount text and split it into contextual segments."""

    raw_value = str(amount_str)
    normalised = (
        raw_value.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    segments = []
    for piece in re.split(r"\n+", normalised):
        segment = re.sub(r"\s+", " ", piece).strip()
        if segment:
            segments.append(segment)

    flattened = re.sub(r"\s+", " ", normalised.replace("\n", " ")).strip()
    return raw_value, segments, flattened


def _extract_amount_fragments(amount_str: Any) -> tuple[str, str, list[AmountFragment]]:
    """Extract numeric fragments from the given amount string."""

    if amount_str is None or amount_str == "" or amount_str == "None":
        return "", "", []

    raw_value, segments, flattened = _prepare_amount_text(amount_str)
    flat_matches = list(_DECIMAL_PATTERN.finditer(flattened))
    flat_index = 0
    fragments: list[AmountFragment] = []

    sign_chars = {"-", "−", "–", "+"}
    negative_chars = {"-", "−", "–"}

    def detect_sign(container: str, start: int, end: int) -> tuple[bool, int]:
        """Detect sign around a numeric fragment within a container string."""

        before_idx = start - 1
        while before_idx >= 0 and container[before_idx].isspace():
            before_idx -= 1
        if before_idx >= 0 and container[before_idx] in sign_chars:
            sign_multiplier = -1 if container[before_idx] in negative_chars else 1
            return True, sign_multiplier

        after_idx = end
        while after_idx < len(container) and container[after_idx].isspace():
            after_idx += 1
        if after_idx < len(container) and container[after_idx] in sign_chars:
            sign_multiplier = -1 if container[after_idx] in negative_chars else 1
            return True, sign_multiplier

        return False, 1

    for segment in segments:
        for match in _DECIMAL_PATTERN.finditer(segment):
            fragment_text = match.group(0).replace(" ", "")
            try:
                magnitude = Decimal(fragment_text.replace(",", "."))
            except (ArithmeticError, ValueError, TypeError):
                continue

            sign = 1
            explicit_sign = False

            explicit_sign, sign = detect_sign(segment, match.start(), match.end())

            flat_match = (
                flat_matches[flat_index] if flat_index < len(flat_matches) else None
            )
            flat_index += 1

            if not explicit_sign and flat_match is not None:
                fallback_detected, fallback_sign = detect_sign(
                    flattened, flat_match.start(), flat_match.end()
                )
                if fallback_detected:
                    explicit_sign = True
                    sign = fallback_sign

            fragments.append(
                AmountFragment(
                    magnitude=magnitude,
                    signed=magnitude * sign,
                    segment_lower=segment.lower(),
                    has_explicit_sign=explicit_sign,
                )
            )

    return raw_value, flattened, fragments


def _apply_contextual_sign(
    fragment: AmountFragment, index: int, column_hint: str
) -> Decimal:
    """Apply contextual hints to determine the effective sign for a fragment."""

    hints = _COLUMN_SIGN_HINTS.get(column_hint, {})
    positive_hints: tuple[str, ...] = hints.get("positive", ())
    negative_hints: tuple[str, ...] = hints.get("negative", ())
    use_alternation: bool = hints.get("alternate", False)

    if fragment.magnitude == 0:
        return Decimal("0.00")

    if fragment.has_explicit_sign and fragment.signed != fragment.magnitude:
        return fragment.signed

    segment_lower = fragment.segment_lower

    if any(keyword in segment_lower for keyword in negative_hints):
        return -fragment.magnitude

    if any(keyword in segment_lower for keyword in positive_hints):
        return fragment.magnitude

    if use_alternation:
        return fragment.magnitude if index % 2 == 0 else -fragment.magnitude

    return fragment.magnitude


def _compute_amount_with_context(
    amount_str: Any, column_hint: str | None = None
) -> Decimal:
    """Compute an amount using contextual hints for plus/minus handling."""

    _, _, fragments = _extract_amount_fragments(amount_str)

    if not fragments:
        return Decimal("0.00")

    if column_hint is None:
        selected: Decimal | None = None
        for fragment in fragments:
            if fragment.signed != 0:
                selected = fragment.signed
        if selected is None:
            selected = fragments[-1].signed
        return selected

    total = Decimal("0.00")
    for index, fragment in enumerate(fragments):
        adjusted = _apply_contextual_sign(fragment, index, column_hint)
        total += adjusted

    return total


def clean_amount(amount_str: Any) -> Decimal:
    """Clean amount string and convert to Decimal."""
    return _compute_amount_with_context(amount_str)


def extract_personal_info_from_text(text_content: str) -> dict[str, Any | date]:
    """Extract personal information from text content."""
    personal_info: dict[str, Any | date] = {}

    # Constants
    months_in_year = 12

    # Split text into lines
    lines = text_content.split("\n")

    for line in lines:
        current_line = line.strip()

        # Look for account number pattern (8 digits or 8 digits with spaces and dashes)
        account_match = re.search(
            r"(\d{8})|(\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1})",
            current_line,
        )
        if account_match and "account_number" not in personal_info:
            # Clean up the account number (remove spaces and dashes)
            account_num = re.sub(r"[\s\-]", "", account_match.group())
            personal_info["account_number"] = account_num

        # Look for full name after "ФИО:"
        if current_line.startswith("ФИО:"):
            name = current_line.replace("ФИО:", "").strip()
            if name and "full_name" not in personal_info:
                personal_info["full_name"] = name

        # Look for address after "Адрес:"
        if current_line.startswith("Адрес:"):
            address = current_line.replace("Адрес:", "").strip()
            if address and "address" not in personal_info:
                personal_info["address"] = address

        # Look for payment period - all months
        months = [
            "январь",
            "февраль",
            "март",
            "апрель",
            "май",
            "июнь",
            "июль",
            "август",
            "сентябрь",
            "октябрь",
            "ноябрь",
            "декабрь",
        ]

        for month in months:
            if month in current_line.lower() and re.search(r"\d{4}", current_line):
                year_match = re.search(r"\d{4}", current_line)
                if year_match:
                    period = f"{month} {year_match.group()}"
                    personal_info["payment_period"] = period
                    break

        # Also check for abbreviated month names
        if "payment_period" not in personal_info:
            month_abbreviations = [
                "янв",
                "фев",
                "мар",
                "апр",
                "мая",
                "июн",
                "июл",
                "авг",
                "сен",
                "окт",
                "ноя",
                "дек",
            ]

            for j, abbr in enumerate(month_abbreviations):
                if abbr in current_line.lower() and re.search(r"\d{4}", current_line):
                    year_match = re.search(r"\d{4}", current_line)
                    if year_match:
                        period = f"{months[j]} {year_match.group()}"
                        personal_info["payment_period"] = period
                        break

        # Also check for numeric month format (MM.YYYY)
        if "payment_period" not in personal_info:
            numeric_month_match = re.search(r"(\d{1,2})\.(\d{4})", current_line)
            if numeric_month_match:
                month_num = int(numeric_month_match.group(1))
                year = numeric_month_match.group(2)
                if 1 <= month_num <= months_in_year:
                    period = f"{months[month_num - 1]} {year}"
                    personal_info["payment_period"] = period

        # Look for due date patterns
        # Pattern 1: "Оплатить до: DD.MM.YYYY"
        due_date_match = re.search(
            r"Оплатить до:\s*(\d{1,2}\.\d{1,2}\.\d{4})", current_line
        )
        if due_date_match and "due_date" not in personal_info:
            try:
                from datetime import datetime

                date_str = due_date_match.group(1)
                due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                personal_info["due_date"] = due_date
            except ValueError:
                pass

        # Pattern 2: "Срок оплаты: DD.MM.YYYY"
        if "due_date" not in personal_info:
            due_date_match = re.search(
                r"Срок оплаты:\s*(\d{1,2}\.\d{1,2}\.\d{4})", current_line
            )
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

        # Pattern 3: "К оплате до: DD.MM.YYYY"
        if "due_date" not in personal_info:
            due_date_match = re.search(
                r"К оплате до:\s*(\d{1,2}\.\d{1,2}\.\d{4})", current_line
            )
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

        # Pattern 4: "Оплатить до DD.MM.YYYY" (without colon)
        if "due_date" not in personal_info:
            due_date_match = re.search(
                r"Оплатить до\s+(\d{1,2}\.\d{1,2}\.\d{4})", current_line
            )
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

        # Pattern 5: "Срок оплаты DD.MM.YYYY" (without colon)
        if "due_date" not in personal_info:
            due_date_match = re.search(
                r"Срок оплаты\s+(\d{1,2}\.\d{1,2}\.\d{4})", current_line
            )
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

        # Pattern 6: Any line containing "до" and date pattern
        if "due_date" not in personal_info and "до" in current_line:
            due_date_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", current_line)
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

    return personal_info


def _table_contains_keywords(
    table_data: list[list[Any]], keywords: tuple[str, ...]
) -> bool:
    """Check if any cell within the table includes the provided keywords."""

    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for row in table_data:
        for cell in row:
            if isinstance(cell, str):
                cell_lower = cell.lower()
                if any(keyword in cell_lower for keyword in lowered_keywords):
                    return True
    return False


def _table_looks_like_service_table(table_data: list[list[Any]]) -> bool:
    """Determine if a table resembles the main services table."""

    minimum_columns_for_service_table = 8
    has_wide_row = any(
        len(row) >= minimum_columns_for_service_table for row in table_data
    )
    return has_wide_row and _table_contains_keywords(table_data, ("тариф", "начислено"))


def _table_looks_like_recalculation_table(table_data: list[list[Any]]) -> bool:
    """Determine if a table likely contains recalculation details."""

    if not _table_contains_keywords(table_data, ("перерасч",)):
        return False

    if _table_looks_like_service_table(table_data):
        return False

    if _table_contains_keywords(table_data, ("тариф", "начислено")):
        return False

    return True


def parse_recalculation_table(table_data: list[list[Any]]) -> list[dict[str, Any]]:
    """Parse recalculation rows from a secondary table."""

    recalculations: list[dict[str, Any]] = []

    for row in table_data:
        if not row:
            continue

        cell_texts = [str(cell).strip() if cell else "" for cell in row]
        if not any(cell_texts):
            continue

        amount_index: int | None = None
        for index in range(len(cell_texts) - 1, -1, -1):
            cell_value = cell_texts[index]
            if not cell_value:
                continue
            _, _, fragments = _extract_amount_fragments(cell_value)
            if fragments:
                amount_index = index
                break

        if amount_index is None:
            continue

        descriptive_parts = [
            part for part in cell_texts[:amount_index] if part and part.lower() != "-"
        ]

        if not descriptive_parts:
            continue

        service_name = descriptive_parts[0]
        service_name_lower = service_name.lower()
        if "вид" in service_name_lower and "услуг" in service_name_lower:
            continue
        if service_name_lower.startswith("перерасч"):
            continue

        reason_parts = descriptive_parts[1:]
        reason = "; ".join(reason_parts)

        if service_name_lower.startswith("итого") or reason.lower().startswith("итого"):
            continue

        amount_value = _compute_amount_with_context(
            cell_texts[amount_index], "recalculation"
        )

        recalculations.append(
            {
                "service_name": service_name,
                "reason": reason,
                "amount": amount_value,
            }
        )

    return recalculations


def parse_services_data(table_data: list[list[Any]]) -> dict[str, Any]:
    """Parse services data from the table."""
    services: dict[str, list[dict[str, Any]]] = {}
    current_category = None

    for row in table_data:
        if not row or not row[0]:
            continue

        service_name = row[0].strip()

        # Check if it's a category header
        if service_name in [
            "Начисления за жилищные услуги",
            "Начисления за коммунальные услуги",
            "Начисления за иные услуги",
        ]:
            current_category = service_name
            services[current_category] = []
            continue

        # Check if it's a total row
        if (
            "Всего за" in service_name
            or "Итого к оплате" in service_name
            or "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ" in service_name
            or "без учета добровольного страхования" in service_name.lower()
            or "с учетом добровольного страхования" in service_name.lower()
        ):
            continue

        # Skip header row
        if service_name == "Виды услуг":
            continue

        # Parse service data
        minimum_row_length = 9
        if current_category and len(row) >= minimum_row_length:
            service_data = {
                "service_name": service_name,
                "volume": row[1] if row[1] and row[1] != "None" else None,
                "unit": row[2] if row[2] and row[2] != "None" else None,
                "tariff": clean_amount(row[3]),
                "amount": clean_amount(row[4]),
                "recalculation": _compute_amount_with_context(row[5], "recalculation"),
                "debt": _compute_amount_with_context(row[6], "debt"),
                "paid": _compute_amount_with_context(row[7], "paid"),
                "total": clean_amount(row[8]),  # Используем итого напрямую из таблицы
            }
            services[current_category].append(service_data)

    return services


def extract_totals(table_data: list[list[Any]]) -> dict[str, Decimal]:
    """Extract total amounts from the table."""
    totals = {}

    for row in table_data:
        if not row or not row[0]:
            continue

        row_text = row[0].strip()

        # Look for various patterns for totals
        if any(
            pattern in row_text
            for pattern in [
                "без учета добровольного страхования",
                "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
            ]
        ):
            amount = clean_amount(row[8])
            totals["total_without_insurance"] = amount
            logger.info(f"Found total without insurance: {amount}")
        elif any(
            pattern in row_text
            for pattern in [
                "с учетом добровольного страхования",
                "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
            ]
        ):
            amount = clean_amount(row[8])
            totals["total_with_insurance"] = amount
            logger.info(f"Found total with insurance: {amount}")
        elif "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ" in row_text:
            amount = clean_amount(row[8])
            totals["insurance_amount"] = amount
            logger.info(f"Found insurance amount: {amount}")

    return totals


def parse_epd_pdf(pdf_file: Any) -> dict[str, Any]:
    """Parse EPD PDF file and return structured data."""
    try:
        # Save uploaded file to temporary location
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            # Write uploaded file content to temporary file
            for chunk in pdf_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        try:
            # Extract tables using pdf2docx
            cv = Converter(temp_file_path)
            tables = cv.extract_tables()
            cv.close()

            # Extract text using pdfplumber
            text_content = ""
            with pdfplumber.open(temp_file_path) as pdf:
                page = pdf.pages[0]
                text_content = page.extract_text()

            # Process all tables from the PDF
            if not tables or len(tables) == 0:
                raise ValueError("No tables found in the PDF")

            # Extract personal info from text content
            personal_info = extract_personal_info_from_text(text_content)

            primary_table = tables[0]

            services_data: dict[str, Any] = {}
            totals: dict[str, Decimal] = {}
            recalculations: list[dict[str, Any]] = []

            for table in tables:
                if not services_data and _table_looks_like_service_table(table):
                    services_data = parse_services_data(table)
                    totals = extract_totals(table)
                elif _table_looks_like_recalculation_table(table):
                    recalculations.extend(parse_recalculation_table(table))

            if not services_data:
                services_data = parse_services_data(primary_table)
                totals = extract_totals(primary_table)

            # Create result structure
            result = {
                "personal_info": personal_info,
                "totals": totals,
                "services": services_data,
                "recalculations": recalculations,
                "text_content": text_content,
            }

            return result

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception:
        raise


def save_epd_document_with_related_data(parsed_data: dict[str, Any]) -> EpdDocument:
    """Save parsed data to Django models."""
    try:
        personal_info = parsed_data.get("personal_info", {})
        totals = parsed_data.get("totals", {})
        services = parsed_data.get("services", {})
        recalculations = parsed_data.get("recalculations", [])

        # Create EPD document
        due_date_value = personal_info.get("due_date")

        # Log the totals for debugging
        logger.info(f"Totals found: {totals}")

        total_without_insurance = totals.get("total_without_insurance", Decimal("0.00"))
        total_with_insurance = totals.get("total_with_insurance", Decimal("0.00"))
        insurance_amount = totals.get("insurance_amount", Decimal("0.00"))

        logger.info(
            f"Creating document with totals: without_insurance={total_without_insurance}, with_insurance={total_with_insurance}, insurance={insurance_amount}"
        )

        document = EpdDocument.objects.create(
            full_name=personal_info.get("full_name", ""),
            address=personal_info.get("address", ""),
            account_number=personal_info.get("account_number", ""),
            payment_period=personal_info.get("payment_period", ""),
            due_date=due_date_value,  # Use extracted due date
            total_without_insurance=total_without_insurance,
            total_with_insurance=total_with_insurance,
            insurance_amount=insurance_amount,
        )

        logger.info(f"Created EPD document with ID: {document.pk}")

        # Save service charges
        order = 1
        total_services = 0

        for services_list in services.values():
            for service_data in services_list:
                ServiceCharge.objects.create(
                    document=document,
                    service_name=service_data["service_name"],
                    volume=(
                        Decimal(str(service_data["volume"]))
                        if service_data["volume"]
                        else None
                    ),
                    unit=service_data["unit"] or "",
                    tariff=service_data["tariff"],
                    amount=service_data["amount"],
                    recalculation=service_data["recalculation"],
                    debt=service_data["debt"],
                    paid=service_data["paid"],
                    total=service_data["total"],
                    order=order,
                )
                order += 1
                total_services += 1

        logger.info(
            f"Saved {total_services} service charges for document {document.pk}"
        )
        recalculation_order = 1
        saved_recalculations = 0

        for recalculation_data in recalculations:
            Recalculation.objects.create(
                document=document,
                service_name=recalculation_data.get("service_name", ""),
                reason=recalculation_data.get("reason", ""),
                amount=recalculation_data.get("amount", Decimal("0.00")),
                order=recalculation_order,
            )
            recalculation_order += 1
            saved_recalculations += 1

        logger.info(
            "Saved %s recalculations for document %s",
            saved_recalculations,
            document.pk,
        )

        return document

    except Exception as e:
        logger.error(f"Error saving EPD document: {e!s}")
        raise

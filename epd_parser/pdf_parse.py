"""PDF parsing module for EPD documents."""

import logging
import os
import re
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pdfplumber
from pdf2docx import Converter

from .models import EpdDocument, ServiceCharge

logger = logging.getLogger(__name__)


def clean_amount(amount_str: Any) -> Decimal:
    """Clean amount string and convert to Decimal."""
    if not amount_str or amount_str == "None":
        return Decimal("0.00")

    cleaned = (
        str(amount_str)
        .replace(" ", "")
        .replace("\xa0", "")
        .replace(",", ".")
        .strip()
    )

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match:
        try:
            return Decimal(match.group())
        except (ValueError, TypeError):
            return Decimal("0.00")
    return Decimal("0.00")


def normalize_header_text(value: Any) -> str:
    """Normalize header cell text for easier comparison.

    Args:
        value: Raw header cell value from the table.

    Returns:
        Normalized string ready for pattern matching.
    """

    if value is None:
        return ""

    text = str(value).lower().replace("\n", " ")
    text = text.replace("ё", "е")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_column_map(header_row: list[Any]) -> dict[str, int]:
    """Build mapping of service fields to table column indices.

    Args:
        header_row: Table row that contains column titles.

    Returns:
        Dictionary mapping known field names to their column indices.
    """

    column_map: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        header_text = normalize_header_text(cell)
        if not header_text:
            continue

        if "объем" in header_text:
            column_map["volume"] = index
        elif any(
            pattern in header_text
            for pattern in ["ед.", "ед изм", "ед. изм", "ед изм."]
        ):
            column_map["unit"] = index
        elif "тариф" in header_text:
            column_map["tariff"] = index
        elif "начислено по тариф" in header_text:
            column_map["amount_by_tariff"] = index
        elif "перерас" in header_text:
            column_map["recalculation"] = index
        elif "начислено" in header_text and "по тариф" not in header_text:
            column_map["amount"] = index
        elif any(
            pattern in header_text
            for pattern in ["долг", "задолж", "переплат", "недоплат"]
        ):
            column_map["debt"] = index
        elif "оплач" in header_text:
            column_map["paid"] = index
        elif "итого" in header_text:
            column_map["total"] = index

    return column_map


def get_cell_value(row: list[Any], index: int | None) -> Any:
    """Return cell value by index with sanity checks.

    Args:
        row: Current table row.
        index: Target column index.

    Returns:
        Cell value if available; otherwise ``None``.
    """

    if index is None or index < 0 or index >= len(row):
        return None

    value = row[index]
    if value in (None, "", "None"):
        return None
    return value


def find_amount_in_row(row: list[Any], preferred_index: int | None = None) -> Decimal:
    """Extract decimal amount from a row using preferred index fallback.

    Args:
        row: Table row to inspect.
        preferred_index: Optional preferred column index.

    Returns:
        Decimal value parsed from the row.
    """

    candidate_indices: list[int] = []
    if preferred_index is not None:
        candidate_indices.append(preferred_index)

    candidate_indices.extend(
        index for index in range(len(row) - 1, -1, -1) if index not in candidate_indices
    )

    for index in candidate_indices:
        if index < 0 or index >= len(row):
            continue
        cell = row[index]
        if cell in (None, "", "None"):
            continue
        text = str(cell).strip()
        if not text:
            continue
        if not re.search(r"\d", text):
            continue
        return clean_amount(text)

    return Decimal("0.00")


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


def parse_services_data(table_data: list[list[Any]]) -> dict[str, Any]:
    """Parse services data from the table."""
    services: dict[str, list[dict[str, Any]]] = {}
    current_category = None
    column_map: dict[str, int] = {}

    for row in table_data:
        if not row:
            continue

        first_cell = row[0]
        if not first_cell:
            continue

        service_name = str(first_cell).strip()

        normalized_first = normalize_header_text(first_cell)
        if "виды услуг" in normalized_first:
            column_map = build_column_map(row)
            continue

        if normalized_first in {
            "начисления за жилищные услуги",
            "начисления за коммунальные услуги",
            "начисления за иные услуги",
        }:
            current_category = service_name
            services[current_category] = []
            continue

        lower_service_name = service_name.lower()
        if (
            "всего за" in lower_service_name
            or "итого к оплате" in lower_service_name
            or "добровольное страхование" in lower_service_name
            or "без учета добровольного страхования" in lower_service_name
            or "с учетом добровольного страхования" in lower_service_name
        ):
            continue

        if not current_category:
            continue

        if not column_map:
            default_map: dict[str, int] = {
                "volume": 1,
                "unit": 2,
                "tariff": 3,
                "recalculation": 5,
            }
            if len(row) >= 10:
                default_map.update(
                    {
                        "amount_by_tariff": 4,
                        "amount": 6,
                        "paid": 7,
                        "debt": 8,
                        "total": 9,
                    }
                )
            else:
                default_map.update(
                    {
                        "amount": 4,
                        "debt": 6,
                        "paid": 7,
                        "total": 8,
                    }
                )
            column_map = default_map

        service_volume = get_cell_value(row, column_map.get("volume"))
        service_unit = get_cell_value(row, column_map.get("unit"))
        tariff_value = get_cell_value(row, column_map.get("tariff"))

        amount_index = column_map.get("amount")
        if amount_index is None:
            amount_index = column_map.get("amount_by_tariff")
        amount_value = get_cell_value(row, amount_index)

        recalculation_value = get_cell_value(row, column_map.get("recalculation"))
        paid_value = get_cell_value(row, column_map.get("paid"))
        debt_value = get_cell_value(row, column_map.get("debt"))

        service_data = {
            "service_name": service_name,
            "volume": service_volume,
            "unit": service_unit,
            "tariff": clean_amount(tariff_value),
            "amount": clean_amount(amount_value),
            "recalculation": clean_amount(recalculation_value),
            "debt": clean_amount(debt_value),
            "paid": clean_amount(paid_value),
            "total": find_amount_in_row(row, column_map.get("total")),
        }
        services.setdefault(current_category, []).append(service_data)

    return services


def extract_totals(table_data: list[list[Any]]) -> dict[str, Decimal]:
    """Extract total amounts from the table."""
    totals: dict[str, Decimal] = {}
    column_map: dict[str, int] = {}

    for row in table_data:
        if not row:
            continue

        first_cell = row[0]
        if not first_cell:
            continue

        normalized_first = normalize_header_text(first_cell)
        if "виды услуг" in normalized_first:
            column_map = build_column_map(row)
            continue

        lower_text = normalized_first

        if "без учета добровольного страхования" in lower_text:
            amount = find_amount_in_row(row, column_map.get("total"))
            totals["total_without_insurance"] = amount
            logger.info(f"Found total without insurance: {amount}")
        elif "с учетом добровольного страхования" in lower_text:
            amount = find_amount_in_row(row, column_map.get("total"))
            totals["total_with_insurance"] = amount
            logger.info(f"Found total with insurance: {amount}")
        elif "добровольное страхование" in lower_text:
            amount = find_amount_in_row(row, column_map.get("total"))
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
            tables = cv.extract_tables(start=0, end=1)
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

            # Use the first table for services and totals (main charges table)
            main_table = tables[0]

            services_data = parse_services_data(main_table)

            totals = extract_totals(main_table)

            # Create result structure
            result = {
                "personal_info": personal_info,
                "totals": totals,
                "services": services_data,
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
        return cast(EpdDocument, document)

    except Exception as e:
        logger.error(f"Error saving EPD document: {e!s}")
        raise

"""PDF parsing module for EPD documents."""

import logging
import re
from decimal import Decimal
from typing import Any, Dict, List

from pdf2docx import Converter
import pdfplumber

from .models import EpdDocument, ServiceCharge, MeterReading, Recalculation

logger = logging.getLogger(__name__)


def clean_amount(amount_str: Any) -> Decimal:
    """Clean amount string and convert to Decimal."""
    if not amount_str or amount_str == "None":
        return Decimal("0.00")

    # Remove spaces and replace comma with dot
    cleaned = str(amount_str).replace(" ", "").replace(",", ".")

    # Extract numeric value
    match = re.search(r"[\d.]+", cleaned)
    if match:
        try:
            return Decimal(match.group())
        except (ValueError, TypeError):
            return Decimal("0.00")
    return Decimal("0.00")


def extract_personal_info_from_text(text_content: str) -> Dict[str, Any]:
    """Extract personal information from text content."""
    personal_info = {}

    # Split text into lines
    lines = text_content.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()

        # Look for account number pattern (8 digits or 8 digits with spaces and dashes)
        account_match = re.search(
            r"(\d{8})|(\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1}\s+\d{1})",
            line,
        )
        if account_match and "account_number" not in personal_info:
            # Clean up the account number (remove spaces and dashes)
            account_num = re.sub(r"[\s\-]", "", account_match.group())
            personal_info["account_number"] = account_num

        # Look for full name after "ФИО:"
        if line.startswith("ФИО:"):
            name = line.replace("ФИО:", "").strip()
            if name and "full_name" not in personal_info:
                personal_info["full_name"] = name

        # Look for address after "Адрес:"
        if line.startswith("Адрес:"):
            address = line.replace("Адрес:", "").strip()
            if address and "address" not in personal_info:
                personal_info["address"] = address

        # Look for payment period
        if "май" in line.lower() and re.search(r"\d{4}", line):
            year_match = re.search(r"\d{4}", line)
            if year_match:
                period = f"май {year_match.group()}"
                personal_info["payment_period"] = period

        # Look for due date patterns
        # Pattern 1: "Оплатить до: DD.MM.YYYY"
        due_date_match = re.search(r"Оплатить до:\s*(\d{1,2}\.\d{1,2}\.\d{4})", line)
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
                r"Срок оплаты:\s*(\d{1,2}\.\d{1,2}\.\d{4})", line
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
                r"К оплате до:\s*(\d{1,2}\.\d{1,2}\.\d{4})", line
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
            due_date_match = re.search(r"Оплатить до\s+(\d{1,2}\.\d{1,2}\.\d{4})", line)
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
            due_date_match = re.search(r"Срок оплаты\s+(\d{1,2}\.\d{1,2}\.\d{4})", line)
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

        # Pattern 6: Any line containing "до" and date pattern
        if "due_date" not in personal_info and "до" in line:
            due_date_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", line)
            if due_date_match:
                try:
                    from datetime import datetime

                    date_str = due_date_match.group(1)
                    due_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    personal_info["due_date"] = due_date
                except ValueError:
                    pass

    return personal_info


def parse_services_data(table_data: List[List[Any]]) -> Dict[str, Any]:
    """Parse services data from the table."""
    services = {}
    current_category = None

    for i, row in enumerate(table_data):
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
            "Всего за май" in service_name
            or "Итого к оплате" in service_name
            or "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ" in service_name
        ):
            continue

        # Skip header row
        if service_name == "Виды услуг":
            continue

        # Parse service data
        if current_category and len(row) >= 9:
            service_data = {
                "service_name": service_name,
                "volume": row[1] if row[1] and row[1] != "None" else None,
                "unit": row[2] if row[2] and row[2] != "None" else None,
                "tariff": clean_amount(row[3]),
                "amount": clean_amount(row[4]),
                "recalculation": clean_amount(row[5]),
                "debt": clean_amount(row[6]),
                "paid": clean_amount(row[7]),
                "total": clean_amount(row[8]),
            }
            services[current_category].append(service_data)

    return services


def extract_totals(table_data: List[List[Any]]) -> Dict[str, Decimal]:
    """Extract total amounts from the table."""
    totals = {}

    for _, row in enumerate(table_data):
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


def parse_epd_pdf(pdf_file) -> Dict[str, Any]:
    """Parse EPD PDF file and return structured data."""
    try:
        # Save uploaded file to temporary location
        import tempfile
        import os

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

    except Exception as e:
        raise


def save_epd_document_with_related_data(parsed_data: Dict[str, Any]) -> EpdDocument:
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

        for category, services_list in services.items():
            for service_data in services_list:
                ServiceCharge.objects.create(
                    document=document,
                    service_name=service_data["service_name"],
                    volume=Decimal(str(service_data["volume"]))
                    if service_data["volume"]
                    else None,
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
        return document

    except Exception as e:
        logger.error(f"Error saving EPD document: {str(e)}")
        raise

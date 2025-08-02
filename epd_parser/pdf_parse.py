import logging
import os
import re
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

# Constants
MIN_LINE_LENGTH = 10


def extract_text_from_pdf(pdf_path: str) -> list[str]:
    """Extract text content from PDF file."""
    with pdfplumber.open(pdf_path) as pdf:
        text_content = []

        for page_num, page in enumerate(pdf.pages, 1):
            print(f"\n=== Page {page_num} ===")

            # Extract text using pdfplumber's text extraction
            page_text = page.extract_text()
            if page_text:
                print("Extracted text:")
                print(page_text)
                text_content.append(page_text)
            else:
                print("No text found on this page")

            # Show character-level information for first few characters
            if page.chars:
                print("\nFirst 5 characters with details:")
                for i, char in enumerate(page.chars[:5]):
                    print(
                        f"  {i + 1}. '{char['text']}' - Position: ({char['x0']:.1f}, {char['y0']:.1f}) - Font: {char['fontname']}"
                    )

        return text_content


def analyze_pdf_structure(pdf_path: str) -> None:
    """Analyze the structure of the PDF document."""
    with pdfplumber.open(pdf_path) as pdf:
        print("\n=== PDF Analysis ===")
        print(f"Total pages: {len(pdf.pages)}")

        for page_num, page in enumerate(pdf.pages, 1):
            print(f"\nPage {page_num}:")
            print(f"  Size: {page.width:.1f} x {page.height:.1f}")
            print(f"  Characters: {len(page.chars)}")
            print(f"  Words: {len(page.extract_words())}")

            # Show unique fonts
            fonts = {char["fontname"] for char in page.chars}
            print(f"  Fonts: {len(fonts)} unique fonts")
            for font in sorted(fonts):
                print(f"    - {font}")


def clean_service_name(service_name: str) -> str:
    """
    Очищает название услуги от числовых данных (volume, unit, tariff).

    Примеры:
    - "ВОДООТВЕДЕНИЕ ОДН 0.00 куб. м. 40.06" -> "ВОДООТВЕДЕНИЕ ОДН"
    - "ХОЛОДНОЕ В/С ОДН 0.00 куб. м. 33.31" -> "ХОЛОДНОЕ В/С ОДН"
    - "ВОДООТВЕДЕНИЕ_ 12.00 куб. м. 40.06" -> "ВОДООТВЕДЕНИЕ"
    """
    # Паттерны для удаления числовых данных из названия
    patterns = [
        # Паттерн: [название] [число] [ед.изм.] [число]
        r"^(.+?)\s+[\d.]+\s+[^\d\s]+\.?\s+[\d.]+$",
        # Паттерн: [название с подчеркиванием] [число] [ед.изм.] [число]
        r"^(.+?[_\s])\s*[\d.]+\s+[^\d\s]+\.?\s+[\d.]+$",
        # Паттерн: [название] [число] [ед.изм.] [число] (с пробелами в единицах)
        r"^(.+?)\s+[\d.]+\s+[^\d]+\s+[\d.]+$",
        # Специальный паттерн для "куб. м." с пробелами
        r"^(.+?)\s+[\d.]+\s+куб\.\s*м\.\s+[\d.]+$",
    ]

    for pattern in patterns:
        match = re.match(pattern, service_name)
        if match:
            return match.group(1).strip()

    return service_name


def extract_volume_unit_from_name(
    service_name: str,
) -> dict[str, str | Decimal | None] | None:
    """
    Извлекает volume и unit из названия услуги.

    Примеры:
    - "ВОДООТВЕДЕНИЕ ОДН 0.00 куб. м. 40.06" -> volume=0.00, unit=куб. м.
    - "ХОЛОДНОЕ В/С ОДН 0.00 куб. м. 33.31" -> volume=0.00, unit=куб. м.
    - "ВОДООТВЕДЕНИЕ_ 12.00 куб. м. 40.06" -> volume=12.00, unit=куб. м.
    """
    # Паттерн для извлечения volume и unit из названия
    patterns = [
        # Паттерн: [название] [число] [ед.изм.] [число] (tariff)
        r"(.+?)\s+([\d.]+)\s+([^\d\s]+\.?)\s+([\d.]+)$",
        # Паттерн: [название] [число] [ед.изм.]
        r"(.+?)\s+([\d.]+)\s+([^\d\s]+\.?)$",
        # Паттерн: [название с подчеркиванием] [число] [ед.изм.] [число]
        r"(.+?[_\s])\s*([\d.]+)\s+([^\d\s]+\.?)\s+([\d.]+)$",
        # Паттерн: [название с подчеркиванием] [число] [ед.изм.]
        r"(.+?[_\s])\s*([\d.]+)\s+([^\d\s]+\.?)$",
        # Паттерн: [название] [число] [ед.изм.] [число] (с пробелами в единицах)
        r"(.+?)\s+([\d.]+)\s+([^\d]+)\s+([\d.]+)$",
        # Паттерн: [название] [число] [ед.изм.] (с пробелами в единицах)
        r"(.+?)\s+([\d.]+)\s+([^\d]+)$",
        # Специальный паттерн для "куб. м." с пробелами
        r"(.+?)\s+([\d.]+)\s+(куб\.\s*м\.)\s+([\d.]+)$",
        r"(.+?)\s+([\d.]+)\s+(куб\.\s*м\.)$",
        # Специальный паттерн для "кВт*ч" (электричество)
        r"(.+?)\s+([\d.]+)\s+(кВт\*ч)\s+([\d.]+)$",
        r"(.+?)\s+([\d.]+)\s+(кВт\*ч)$",
        # Специальный паттерн для "Гкал" (тепло)
        r"(.+?)\s+([\d.]+)\s+(Гкал)\s+([\d.]+)$",
        r"(.+?)\s+([\d.]+)\s+(Гкал)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, service_name)
        if match:
            try:
                if len(match.groups()) == 4:
                    # Паттерн: название + volume + unit + tariff
                    volume = Decimal(match.group(2))
                    unit = match.group(3).strip()
                    return {"volume": volume, "unit": unit}
                elif len(match.groups()) == 3:
                    # Паттерн: название + volume + unit
                    volume = Decimal(match.group(2))
                    unit = match.group(3).strip()
                    return {"volume": volume, "unit": unit}
            except (ValueError, TypeError):
                continue

    return None


def extract_tariff_from_name(service_name: str) -> Decimal | None:
    """
    Извлекает tariff из названия услуги.

    Примеры:
    - "ВОДООТВЕДЕНИЕ ОДН 0.00 куб. м. 40.06" -> 40.06
    - "ХОЛОДНОЕ В/С ОДН 0.00 куб. м. 33.31" -> 33.31
    """
    # Паттерн для извлечения tariff из названия
    patterns = [
        # Паттерн: [название] [число] [ед.изм.] [число] (tariff - последнее число)
        r"(.+?)\s+([\d.]+)\s+([^\d\s]+\.?)\s+([\d.]+)$",
        # Паттерн: [название с подчеркиванием] [число] [ед.изм.] [число]
        r"(.+?[_\s])\s*([\d.]+)\s+([^\d\s]+\.?)\s+([\d.]+)$",
        # Паттерн: [название] [число] [ед.изм.] [число] (с пробелами в единицах)
        r"(.+?)\s+([\d.]+)\s+([^\d]+)\s+([\d.]+)$",
        # Специальный паттерн для "куб. м." с пробелами
        r"(.+?)\s+([\d.]+)\s+(куб\.\s*м\.)\s+([\d.]+)$",
        # Специальный паттерн для "кВт*ч" (электричество)
        r"(.+?)\s+([\d.]+)\s+(кВт\*ч)\s+([\d.]+)$",
        # Специальный паттерн для "Гкал" (тепло)
        r"(.+?)\s+([\d.]+)\s+(Гкал)\s+([\d.]+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, service_name)
        if match:
            try:
                # Tariff - это последнее число в паттерне
                tariff_str = match.group(4)
                return Decimal(tariff_str)
            except (ValueError, TypeError):
                continue

    return None


def parse_service_line(line: str) -> dict[str, str | Decimal | None] | None:
    """
    Универсальный парсер строки услуги с учетом структуры таблицы.
    Поддерживает форматы: [название] [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    """
    import re
    from decimal import Decimal, InvalidOperation

    # Удаляем лишние пробелы
    line = " ".join(line.split())

    # Функция для нормализации чисел (убираем пробелы, заменяем запятые на точки)
    def normalize_number(num_str: str) -> str:
        # Убираем все пробелы и заменяем запятые на точки
        normalized = num_str.replace(" ", "").replace(",", ".")
        return normalized

    # Функция для безопасной конвертации в Decimal
    def safe_decimal(value: str) -> Decimal | None:
        try:
            normalized = normalize_number(value)
            return Decimal(normalized)
        except (ValueError, InvalidOperation):
            return None

    # Паттерн 1: Полный формат с названием услуги и 8 числовыми колонками
    # [название услуги] [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern1 = (
        r"^(?P<service_name>.+?)\s+"
        r"(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern1, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])
            recalculation = safe_decimal(d["recalculation"])
            debt = safe_decimal(d["debt"])
            paid = safe_decimal(d["paid"])
            total = safe_decimal(d["total"])

            if all(
                v is not None
                for v in [volume, tariff, amount, recalculation, debt, paid, total]
            ):
                result = {
                    "service_name": d["service_name"].strip(),
                    "volume": volume,
                    "unit": d["unit"].strip(),
                    "tariff": tariff,
                    "amount": amount,
                    "recalculation": recalculation,
                    "debt": debt,
                    "paid": paid,
                    "total": total,
                }

                # Очищаем название услуги от числовых данных
                result["service_name"] = clean_service_name(result["service_name"])

                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 2: Формат с названием услуги и 7 числовыми колонками (без тарифа)
    # [название услуги] [объем] [ед.изм.] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern2 = (
        r"^(?P<service_name>.+?)\s+"
        r"(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern2, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            amount = safe_decimal(d["amount"])
            recalculation = safe_decimal(d["recalculation"])
            debt = safe_decimal(d["debt"])
            paid = safe_decimal(d["paid"])
            total = safe_decimal(d["total"])

            if all(
                v is not None
                for v in [volume, amount, recalculation, debt, paid, total]
            ):
                result = {
                    "service_name": d["service_name"].strip(),
                    "volume": volume,
                    "unit": d["unit"].strip(),
                    "tariff": None,
                    "amount": amount,
                    "recalculation": recalculation,
                    "debt": debt,
                    "paid": paid,
                    "total": total,
                }

                # Попробуем извлечь tariff из названия
                extracted_tariff = extract_tariff_from_name(d["service_name"].strip())
                if extracted_tariff:
                    result["tariff"] = extracted_tariff

                # Очищаем название услуги от числовых данных
                result["service_name"] = clean_service_name(result["service_name"])

                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 3: Формат с названием услуги и 6 числовыми колонками (только суммы)
    # [название услуги] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern3 = (
        r"^(?P<service_name>.+?)\s+"
        r"(?P<amount>[\d\s,]+)\s+"
        r"(?P<recalculation>[\d\s,]+)\s+"
        r"(?P<debt>[\d\s,]+)\s+"
        r"(?P<paid>[\d\s,]+)\s+"
        r"(?P<total>[\d\s,]+)$"
    )

    match = re.match(pattern3, line)
    if match:
        try:
            d = match.groupdict()
            amount = safe_decimal(d["amount"])
            recalculation = safe_decimal(d["recalculation"])
            debt = safe_decimal(d["debt"])
            paid = safe_decimal(d["paid"])
            total = safe_decimal(d["total"])

            if all(v is not None for v in [amount, recalculation, debt, paid, total]):
                result = {
                    "service_name": d["service_name"].strip(),
                    "volume": None,
                    "unit": None,
                    "tariff": None,
                    "amount": amount,
                    "recalculation": recalculation,
                    "debt": debt,
                    "paid": paid,
                    "total": total,
                }

                # Попробуем извлечь volume, unit и tariff из названия
                volume_unit = extract_volume_unit_from_name(d["service_name"].strip())
                if volume_unit:
                    result["volume"] = volume_unit["volume"]
                    result["unit"] = volume_unit["unit"]

                extracted_tariff = extract_tariff_from_name(d["service_name"].strip())
                if extracted_tariff:
                    result["tariff"] = extracted_tariff

                # Очищаем название услуги от числовых данных
                result["service_name"] = clean_service_name(result["service_name"])

                return result
        except (ValueError, TypeError):
            pass

    return None


def parse_services(text_content: str) -> list:
    """
    Parse services from EPD document table with support for multi-line service names.

    Args:
        text_content: Extracted text from PDF

    Returns:
        List of dictionaries with service data
    """
    services = []

    # Split text into lines for easier processing
    lines = text_content.split("\n")

    # Find the services table section
    in_services_section = False
    current_service_name = ""
    current_service_data = None

    for line in lines:
        # Look for the start of services table
        if "РАСЧЕТ РАЗМЕРА ПЛАТЫ" in line or "Начисления за" in line:
            in_services_section = True
            continue

        # Stop when we reach the end of services
        if in_services_section and ("Всего за" in line or "Итого к оплате" in line):
            break

        if in_services_section and line.strip():
            # Проверяем, является ли это строкой с данными услуги
            if is_service_data_line(line):
                # Проверяем, содержит ли строка volume/unit/tariff и числа
                if re.search(r"[\d.]+ [^\d\s]+\.? [\d.]+", line):
                    # Это строка с volume/unit/tariff и данными
                    if current_service_name:
                        # Объединяем название с данными
                        full_line = f"{current_service_name} {line.strip()}"
                        service_data = parse_service_line(full_line)
                        if service_data:
                            services.append(service_data)
                        current_service_name = ""
                        current_service_data = None
                    else:
                        # Парсим как однострочную услугу
                        service_data = parse_service_line(line)
                        if service_data:
                            services.append(service_data)
                else:
                    # Это строка с только числами - многострочная услуга
                    if current_service_name:
                        service_data = parse_multiline_service(line)
                        if service_data:
                            service_data["service_name"] = current_service_name

                            # Попробуем извлечь volume, unit и tariff из названия услуги
                            volume_unit = extract_volume_unit_from_name(
                                current_service_name
                            )
                            if volume_unit:
                                service_data["volume"] = volume_unit["volume"]
                                service_data["unit"] = volume_unit["unit"]

                            extracted_tariff = extract_tariff_from_name(
                                current_service_name
                            )
                            if extracted_tariff:
                                service_data["tariff"] = extracted_tariff

                            services.append(service_data)
                        current_service_name = ""
                        current_service_data = None
                    else:
                        # Если нет сохраненного названия, пропускаем строку
                        continue
            else:
                # Это строка с названием услуги
                if is_service_name_line(line):
                    # Проверяем, содержит ли название услуги данные
                    if contains_service_data(line):
                        # Парсим как однострочную услугу с данными в названии
                        service_data = parse_service_line(line)
                        if service_data:
                            services.append(service_data)
                        else:
                            # Если не удалось распарсить, но строка содержит данные,
                            # попробуем извлечь volume, unit и tariff из названия
                            volume_unit = extract_volume_unit_from_name(line)
                            if volume_unit:
                                # Попробуем также извлечь tariff
                                tariff = extract_tariff_from_name(line)
                                # Извлекаем числовые данные из строки
                                numbers = re.findall(r"[\d\s,]+[.,]\d{2}", line)
                                if len(numbers) >= 5:
                                    # Создаем базовую структуру услуги с данными
                                    service_data = {
                                        "service_name": clean_service_name(
                                            line.strip()
                                        ),
                                        "volume": volume_unit["volume"],
                                        "unit": volume_unit["unit"],
                                        "tariff": tariff,
                                        "amount": Decimal(
                                            numbers[0]
                                            .replace(" ", "")
                                            .replace(",", ".")
                                        ),
                                        "recalculation": Decimal(
                                            numbers[1]
                                            .replace(" ", "")
                                            .replace(",", ".")
                                        ),
                                        "debt": Decimal(
                                            numbers[2]
                                            .replace(" ", "")
                                            .replace(",", ".")
                                        ),
                                        "paid": Decimal(
                                            numbers[3]
                                            .replace(" ", "")
                                            .replace(",", ".")
                                        ),
                                        "total": Decimal(
                                            numbers[4]
                                            .replace(" ", "")
                                            .replace(",", ".")
                                        ),
                                    }
                                    services.append(service_data)
                                else:
                                    # Создаем базовую структуру услуги без числовых данных
                                    service_data = {
                                        "service_name": clean_service_name(
                                            line.strip()
                                        ),
                                        "volume": volume_unit["volume"],
                                        "unit": volume_unit["unit"],
                                        "tariff": tariff,
                                        "amount": None,
                                        "recalculation": None,
                                        "debt": None,
                                        "paid": None,
                                        "total": None,
                                    }
                                    services.append(service_data)
                            else:
                                # Сохраняем название для следующей строки
                                current_service_name = line.strip()
                    else:
                        current_service_name = line.strip()
                # Пропускаем заголовки и пустые строки
                elif not should_skip_line(line):
                    continue
    return services


def is_service_data_line(line: str) -> bool:
    """
    Проверяет, является ли строка данными услуги (содержит числа в конце).
    """
    # Ищем числа в формате: цифры + пробелы + запятая/точка + 2 цифры в конце строки
    has_numbers_at_end = bool(re.search(r"[\d\s,]+[.,]\d{2}\s*$", line))

    # Если строка содержит ключевые слова услуг, то это не данные, а название
    service_keywords = [
        "РЕМОНТ",
        "СОДЕРЖАНИЕ",
        "ВОДООТВЕДЕНИЕ",
        "ГОРЯЧЕЕ",
        "ХОЛОДНОЕ",
        "ЭЛЕКТРО",
        "ОТОПЛЕНИЕ",
        "ОБРАЩЕНИЕ",
        "ОПЛАТА",
        "ТО ИТП",
        "ДОБРОВОЛЬНОЕ",
        "ЭЛЕКТРИЧЕСТВО",
        "ЭЛЕКТРОСНАБЖЕНИЕ",
    ]

    has_service_keywords = any(keyword in line.upper() for keyword in service_keywords)

    # Если есть ключевые слова услуг, то это название, а не данные
    if has_service_keywords:
        return False

    return has_numbers_at_end


def is_service_name_line(line: str) -> bool:
    """
    Проверяет, является ли строка названием услуги.
    """
    service_keywords = [
        "РЕМОНТ",
        "СОДЕРЖАНИЕ",
        "ВОДООТВЕДЕНИЕ",
        "ГОРЯЧЕЕ",
        "ХОЛОДНОЕ",
        "ЭЛЕКТРО",
        "ОТОПЛЕНИЕ",
        "ОБРАЩЕНИЕ",
        "ОПЛАТА",
        "ТО ИТП",
        "ДОБРОВОЛЬНОЕ",
        "ЭЛЕКТРИЧЕСТВО",
        "ЭЛЕКТРОСНАБЖЕНИЕ",
    ]

    # Проверяем наличие ключевых слов
    has_keyword = any(keyword in line.upper() for keyword in service_keywords)

    # Если есть ключевые слова, то это название услуги
    if has_keyword:
        return True

    return False


def should_skip_line(line: str) -> bool:
    """
    Проверяет, нужно ли пропустить строку.
    """
    skip_patterns = [
        "Объем",
        "Ед.изм",
        "Тариф",
        "Начислено",
        "Перерасчеты",
        "Задолженность",
        "Оплачено",
        "ИТОГО",
    ]
    skip_sections = [
        "Начисления за жилищные услуги",
        "Начисления за коммунальные услуги",
        "Начисления за иные услуги",
    ]

    line_upper = line.upper()
    return (
        not line.strip()
        or any(pattern in line_upper for pattern in skip_patterns)
        or line.strip() in skip_sections
    )


def contains_service_data(line: str) -> bool:
    """
    Проверяет, содержит ли строка данные услуги (числа с копейками).
    """
    # Ищем числа в формате: цифры + пробелы + запятая/точка + 2 цифры
    return bool(re.search(r"[\d\s,]+[.,]\d{2}", line))


def parse_multiline_service(line: str) -> dict[str, str | Decimal | None] | None:
    """
    Специальный парсер для многострочных услуг типа:
    "68.90 кв.м. 22.00 1 515,80 0,00 1 240,20 1 240,20 1 515,80"
    """
    import re
    from decimal import Decimal, InvalidOperation

    # Удаляем лишние пробелы
    line = " ".join(line.split())

    # Функция для нормализации чисел (убираем пробелы, заменяем запятые на точки)
    def normalize_number(num_str: str) -> str:
        # Убираем все пробелы и заменяем запятые на точки
        normalized = num_str.replace(" ", "").replace(",", ".")
        return normalized

    # Функция для безопасной конвертации в Decimal
    def safe_decimal(value: str) -> Decimal | None:
        try:
            normalized = normalize_number(value)
            return Decimal(normalized)
        except (ValueError, InvalidOperation):
            return None

    # Паттерн: [volume] [unit] [tariff] [amount] [recalculation] [debt] [paid] [total]
    # Колонки: [volume] [unit] [tariff] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern, line)
    if match:
        try:
            d = match.groupdict()

            return {
                "service_name": None,  # Будет добавлено в parse_services
                "volume": safe_decimal(d["volume"]),
                "unit": d["unit"].strip(),
                "tariff": safe_decimal(d["tariff"]),
                "amount": safe_decimal(d["amount"]),
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }
        except (ValueError, TypeError):
            pass

    # Специальный парсер для строк с только числами (5 чисел)
    # Пример: "0,00 30,30 16,36 16,36 30,30"
    # Колонки: [начислено] [перерасчет] [долг] [оплачено] [итого]
    numbers_only_pattern = r"^([\d\s,]+[.,]\d{2})\s+([\d\s,]+[.,]\d{2})\s+([\d\s,]+[.,]\d{2})\s+([\d\s,]+[.,]\d{2})\s+([\d\s,]+[.,]\d{2})$"

    match = re.match(numbers_only_pattern, line)
    if match:
        try:
            numbers = [safe_decimal(match.group(i)) for i in range(1, 6)]
            if all(num is not None for num in numbers):
                return {
                    "service_name": None,  # Будет добавлено в parse_services
                    "volume": None,
                    "unit": None,
                    "tariff": None,
                    "amount": numbers[0],  # Начислено по тарифу
                    "recalculation": numbers[1],  # Перерасчеты
                    "debt": numbers[2],  # Задолженность
                    "paid": numbers[3],  # Оплачено
                    "total": numbers[4],  # ИТОГО
                }
        except (ValueError, TypeError):
            pass

    # Дополнительный паттерн для строк с volume, unit и 5 числами
    # Пример: "38 кВт*ч 3.49 132.62 0.00 0.00 0.00 0.00"
    # Колонки: [volume] [unit] [tariff] [начислено] [перерасчет] [долг] [оплачено] [итого]
    volume_unit_numbers_pattern = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(volume_unit_numbers_pattern, line)
    if match:
        try:
            d = match.groupdict()
            return {
                "service_name": None,  # Будет добавлено в parse_services
                "volume": safe_decimal(d["volume"]),
                "unit": d["unit"].strip(),
                "tariff": safe_decimal(d["tariff"]),
                "amount": safe_decimal(d["amount"]),
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }
        except (ValueError, TypeError):
            pass

    return None


def parse_epd_data(text_content: str) -> dict[str, Any]:
    """
    Parse EPD document data from extracted text.

    Args:
        text_content: Extracted text from PDF

    Returns:
        Dictionary with parsed data
    """
    data = {}

    # Extract account number (Лицевой счет)
    account_pattern = r"Лицевой счет:\s*([\d\s\-]+)"
    account_match = re.search(account_pattern, text_content)
    if account_match:
        # Remove spaces, keep dash (or remove dash if you want just digits)
        account_number = account_match.group(1).replace(" ", "")
        data["account_number"] = account_number
        print(f"Found account number: {account_number}")

    # Extract full name (ФИО)
    fio_pattern = r"ФИО:\s*([А-ЯЁ\s]+?)(?:\n|$)"
    fio_match = re.search(fio_pattern, text_content)
    if fio_match:
        full_name = fio_match.group(1).strip()
        data["full_name"] = full_name
        print(f"Found full name: {full_name}")

    # Extract address (Адрес)
    address_pattern = r"Адрес:\s*([^\n]+?)(?:\n|$)"
    address_match = re.search(address_pattern, text_content)
    if address_match:
        address = address_match.group(1).strip()
        data["address"] = address
        print(f"Found address: {address}")

    # Extract payment period (месяц и год)
    period_pattern = r"ЗА\s+([а-яё]+)\s+(\d{4})\s+г\."
    period_match = re.search(period_pattern, text_content)
    if period_match:
        month = period_match.group(1)
        year = period_match.group(2)
        # Convert month name to number
        month_map = {
            "январь": "01",
            "февраль": "02",
            "март": "03",
            "апрель": "04",
            "май": "05",
            "июнь": "06",
            "июль": "07",
            "август": "08",
            "сентябрь": "09",
            "октябрь": "10",
            "ноябрь": "11",
            "декабрь": "12",
        }
        month_num = month_map.get(month.lower(), "01")
        payment_period = f"{month_num}.{year}"
        data["payment_period"] = payment_period
        print(f"Found payment period: {payment_period}")

    # Extract due date (до какого числа оплатить)
    due_date_pattern = r"Просим оплатить счет до\s+(\d{2})\.(\d{2})\.(\d{4})"
    due_date_match = re.search(due_date_pattern, text_content)
    if due_date_match:
        day, month, year = due_date_match.groups()
        due_date = f"{year}-{month}-{day}"
        data["due_date"] = due_date
        print(f"Found due date: {due_date}")

    # Extract total without insurance - try multiple patterns
    total_without_patterns = [
        r"Итого к оплате за [а-яё\s]+ без учета добровольного страхования:\s*([\d\s,]+)\s*руб",
        r"Всего за [а-яё\s]+ без учета добровольного страхования:\s*([\d\s,]+)\s*руб",
        r"без учета добровольного страхования[^\d]*([\d\s,]+)\s*руб",
        r"Итого к оплате за [а-яё\s]+ без учета добровольного страхования:\s*([\d\s,]+)",
        r"Всего за [а-яё\s]+ без учета добровольного страхования:\s*([\d\s,]+)",
        # More specific patterns based on actual text
        r"Итого к оплате за июль 2025 без учета добровольного страхования:\s*([\d\s,]+)",
        r"Всего за июль 2025 без учета добровольного страхования:\s*([\d\s,]+)",
    ]

    for pattern in total_without_patterns:
        total_without_match = re.search(pattern, text_content)
        if total_without_match:
            amount_str = total_without_match.group(1).replace(" ", "").replace(",", ".")
            try:
                total_without = Decimal(amount_str)
                data["total_without_insurance"] = total_without
                print(f"Found total without insurance: {total_without}")
                break
            except (ValueError, TypeError):
                print(f"Could not parse total without insurance: {amount_str}")

    # Extract total with insurance - try multiple patterns
    total_with_patterns = [
        r"Итого к оплате за [а-яё\s]+ с учетом добровольного страхования:\s*([\d\s,]+)\s*руб",
        r"Всего за [а-яё\s]+ с учетом добровольного страхования[^\d]*([\d\s,]+)\s*руб",
        r"с учетом добровольного страхования[^\d]*([\d\s,]+)\s*руб",
        r"Итого к оплате за [а-яё\s]+ с учетом добровольного страхования:\s*([\d\s,]+)",
        r"Всего за [а-яё\s]+ с учетом добровольного страхования:\s*([\d\s,]+)",
        # More specific patterns based on actual text
        r"Итого к оплате за июль 2025 с учетом добровольного страхования:\s*([\d\s,]+)",
        r"Всего за июль 2025 с учетом добровольного страхования:\s*([\d\s,]+)",
    ]

    for pattern in total_with_patterns:
        total_with_match = re.search(pattern, text_content)
        if total_with_match:
            amount_str = total_with_match.group(1).replace(" ", "").replace(",", ".")
            try:
                total_with = Decimal(amount_str)
                data["total_with_insurance"] = total_with
                print(f"Found total with insurance: {total_with}")
                break
            except (ValueError, TypeError):
                print(f"Could not parse total with insurance: {amount_str}")

    # Parse services
    services = parse_services(text_content)
    data["services"] = services
    print(f"Found {len(services)} services")

    return data


def parse_epd_pdf(pdf_file) -> Dict[str, Any]:
    """
    Parse EPD PDF file and return structured data ready for Django models.

    Args:
        pdf_file: Django UploadedFile object or file path

    Returns:
        Dictionary with parsed EPD data including:
        - account_number: str
        - full_name: str
        - address: str
        - payment_period: str
        - due_date: str (YYYY-MM-DD format)
        - total_without_insurance: Decimal
        - total_with_insurance: Decimal
        - services: List[Dict] - service charges data
        - meter_readings: List[Dict] - meter readings data
        - recalculations: List[Dict] - recalculation data

    Raises:
        ValidationError: If PDF cannot be parsed or required data is missing
        Exception: For other parsing errors
    """
    logger.info("Starting EPD PDF parsing")

    temp_file_path = None

    try:
        # Handle both file objects and file paths
        if hasattr(pdf_file, "name"):
            # Django UploadedFile object
            logger.info(f"Processing uploaded file: {pdf_file.name}")

            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                for chunk in pdf_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
                logger.info(f"Saved temporary file: {temp_file_path}")
        else:
            # File path string
            temp_file_path = str(pdf_file)
            logger.info(f"Processing file at path: {temp_file_path}")

        # Validate file exists
        if not os.path.exists(temp_file_path):
            raise ValidationError(_("PDF file not found"))

        # Extract text content
        logger.info("Extracting text from PDF")
        text_content = extract_text_from_pdf(temp_file_path)

        if not text_content:
            raise ValidationError(_("No text content found in PDF"))

        # Parse EPD data
        logger.info("Parsing EPD data from extracted text")
        full_text = "\n".join(text_content)
        parsed_data = parse_epd_data(full_text)

        # Validate required fields
        required_fields = ["account_number", "full_name", "address", "payment_period"]
        missing_fields = [
            field for field in required_fields if not parsed_data.get(field)
        ]

        if missing_fields:
            raise ValidationError(
                _("Required fields missing from PDF: {fields}").format(
                    fields=", ".join(missing_fields)
                )
            )

        # Validate financial data
        if not parsed_data.get("total_without_insurance"):
            logger.warning("Total without insurance not found in PDF")
            parsed_data["total_without_insurance"] = Decimal("0.00")

        if not parsed_data.get("total_with_insurance"):
            logger.warning("Total with insurance not found in PDF")
            parsed_data["total_with_insurance"] = Decimal("0.00")

        # Validate services
        if not parsed_data.get("services"):
            logger.warning("No services found in PDF")
            parsed_data["services"] = []

        logger.info(
            f"Successfully parsed EPD data: {len(parsed_data.get('services', []))} services found"
        )

        return parsed_data

    except ValidationError:
        # Re-raise validation errors
        raise
    except Exception as e:
        logger.error(f"Error parsing EPD PDF: {e}")
        raise ValidationError(
            _("Failed to parse PDF file: {error}").format(error=str(e))
        )
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info("Temporary file cleaned up")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")


def create_epd_document_from_parsed_data(
    parsed_data: Dict[str, Any], pdf_file=None
) -> Any:  # Using Any instead of "EpdDocument" to avoid circular imports
    """
    Create EpdDocument instance from parsed data.

    Args:
        parsed_data: Dictionary with parsed EPD data
        pdf_file: Optional Django UploadedFile for saving

    Returns:
        EpdDocument instance (not saved to database)
    """
    from .models import EpdDocument, ServiceCharge, MeterReading, Recalculation

    logger.info("Creating EpdDocument from parsed data")

    # Create main document
    document = EpdDocument(
        full_name=parsed_data["full_name"],
        address=parsed_data["address"],
        account_number=parsed_data["account_number"],
        payment_period=parsed_data["payment_period"],
        due_date=parsed_data["due_date"]
        if hasattr(parsed_data["due_date"], "year")
        else datetime.strptime(parsed_data["due_date"], "%Y-%m-%d").date(),
        total_without_insurance=parsed_data["total_without_insurance"],
        total_with_insurance=parsed_data["total_with_insurance"],
    )

    if pdf_file:
        document.pdf_file = pdf_file

    # Note: Don't save here - let the calling code handle saving
    # This allows for transaction management and validation

    return document


def save_epd_document_with_related_data(
    parsed_data: Dict[str, Any],
    pdf_file=None,
    form_data: Optional[Dict[str, Any]] = None,
) -> Any:  # Using Any instead of "EpdDocument" to avoid circular imports
    """
    Save EpdDocument and all related data to database.

    Args:
        parsed_data: Dictionary with parsed EPD data
        pdf_file: Optional Django UploadedFile for saving
        form_data: Optional form data to override parsed data

    Returns:
        Saved EpdDocument instance
    """
    from django.db import transaction
    from .models import EpdDocument, ServiceCharge, MeterReading, Recalculation

    logger.info("Saving EPD document with related data to database")

    with transaction.atomic():
        # Use form data if provided, otherwise use parsed data
        data_to_use = form_data if form_data is not None else parsed_data

        # Create and save main document
        document = create_epd_document_from_parsed_data(data_to_use, pdf_file)
        document.save()

        # Save service charges
        for i, service_data in enumerate(parsed_data.get("services", [])):
            service_charge = ServiceCharge(
                document=document,
                service_name=service_data["service_name"],
                volume=service_data.get("volume"),
                tariff=service_data.get("tariff"),
                amount=service_data["amount"],
                recalculation=service_data.get("recalculation", Decimal("0.00")),
                debt=service_data.get("debt", Decimal("0.00")),
                paid=service_data.get("paid", Decimal("0.00")),
                total=service_data["total"],
                order=i + 1,
            )
            # Сохраняем без пересчета total, так как значение уже правильное из парсера
            service_charge.save(recalculate_total=False)

        # Save meter readings (if available)
        for i, meter_data in enumerate(parsed_data.get("meter_readings", [])):
            meter_reading = MeterReading(
                document=document,
                service_name=meter_data["service_name"],
                meter_type=meter_data.get("meter_type", ""),
                meter_number=meter_data.get("meter_number", ""),
                verification_date=meter_data.get("verification_date"),
                previous_reading=meter_data.get("previous_reading"),
                current_reading=meter_data.get("current_reading"),
                order=i + 1,
            )
            meter_reading.save()

        # Save recalculations (if available)
        for i, recalculation_data in enumerate(parsed_data.get("recalculations", [])):
            recalculation = Recalculation(
                document=document,
                service_name=recalculation_data["service_name"],
                reason=recalculation_data.get("reason", ""),
                amount=recalculation_data["amount"],
                order=i + 1,
            )
            recalculation.save()

    logger.info(
        f"Successfully saved EPD document {document.id} with {len(parsed_data.get('services', []))} services"
    )
    return document


if __name__ == "__main__":
    pdf_path = "/home/alexander/Downloads/01-07-2025.pdf"

    try:
        # Extract text content
        text_content = extract_text_from_pdf(pdf_path)

        # Analyze PDF structure
        analyze_pdf_structure(pdf_path)

        # Parse EPD data
        if text_content:
            full_text = "\n".join(text_content)
            parsed_data = parse_epd_data(full_text)
            print("\n=== Parsed Data ===")
            for key, value in parsed_data.items():
                print(f"{key}: {value}")

        print("\n=== Summary ===")
        print(f"Successfully processed PDF: {pdf_path}")
        print(f"Total pages with text: {len(text_content)}")

    except FileNotFoundError:
        print(f"Error: PDF file not found at {pdf_path}")
    except Exception as e:
        print(f"Error processing PDF: {e}")

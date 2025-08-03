import logging
import os
import re
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .models import EpdDocument, MeterReading, Recalculation, ServiceCharge

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
    - "56.50 кв.м." -> "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ" (определяется по контексту)
    """
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не название услуги
    if any(keyword in service_name.upper() for keyword in exclude_keywords):
        return ""

    # Сначала проверяем, является ли строка только числовыми данными
    if re.match(r"^[\d.]+\s+[^\d\s]+\.?$", service_name.strip()):
        # Это только volume + unit, нужно определить название по контексту
        # Пока возвращаем как есть, название будет определено позже
        return service_name.strip()

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
        # Паттерн: [название] [число] [ед.изм.]
        r"^(.+?)\s+[\d.]+\s+[^\d\s]+\.?$",
        # Паттерн: [название] [число] [ед.изм.] (с пробелами в единицах)
        r"^(.+?)\s+[\d.]+\s+[^\d]+$",
    ]

    for pattern in patterns:
        match = re.match(pattern, service_name)
        if match:
            cleaned_name = match.group(1).strip()
            # Проверяем, что очищенное название не пустое и содержит буквы
            if cleaned_name and re.search(r"[А-ЯЁ]", cleaned_name):
                return cleaned_name

    return service_name.strip()


def determine_service_name_by_context(
    volume: Decimal, unit: str, tariff: Decimal, amount: Decimal
) -> str:
    """
    Определяет название услуги по контексту (volume, unit, tariff, amount).

    Args:
        volume: Объем услуги
        unit: Единица измерения
        tariff: Тариф
        amount: Сумма начисления

    Returns:
        Название услуги
    """
    # Определяем услугу по комбинации параметров
    if unit == "кв.м.":
        if tariff == Decimal("22.00"):
            return "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ"
        elif tariff == Decimal("38.61"):
            return "СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ"
        elif tariff == Decimal("11.334"):
            return "ОБРАЩЕНИЕ С ТКО"
        elif tariff == Decimal("4.20"):
            # Проверяем, не является ли это строкой "Всего за июль"
            large_volume_threshold = 1000
            if (
                volume and volume > large_volume_threshold
            ):  # Если объем очень большой, это скорее всего итоговая строка
                return "ИТОГО"
            else:
                return "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ"

    elif unit == "куб. м.":
        if "ОДН" in str(volume):  # Если в volume есть упоминание ОДН
            if tariff == Decimal("61.19"):
                return "ВОДООТВЕДЕНИЕ ОДН"
            elif tariff == Decimal("62.22"):
                return "ХОЛОДНОЕ В/С ОДН"
        elif tariff == Decimal("61.19"):
            return "ВОДООТВЕДЕНИЕ"
        elif tariff == Decimal("62.22"):
            return "ХОЛОДНОЕ В/С"

    elif unit == "куб.м.":
        if tariff == Decimal("62.22"):
            return "ГОРЯЧАЯ ВОДА (НОСИТЕЛЬ) ОДН"
        elif tariff == Decimal("2774.75"):
            return "ГОРЯЧЕЕ В/С (ЭНЕРГИЯ)"

    elif unit == "Гкал":
        if tariff == Decimal("2774.75"):
            return "ОТОПЛЕНИЕ"

    elif unit == "кВт*ч":
        if tariff == Decimal("6.19"):
            return "ЭЛЕКТРОСНАБЖЕНИЕ ОДН"

    elif unit == "абонент":
        if tariff == Decimal("50.00"):
            return "ЗАПИРАЮЩЕЕ УСТРОЙСТВО"
        elif tariff == Decimal("118.83"):
            return "ТО ВКГО"

    # Если не удалось определить, возвращаем общее название
    return f"УСЛУГА ({unit})"


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
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не название услуги
    if any(keyword in service_name.upper() for keyword in exclude_keywords):
        return None

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
                groups_with_tariff = 4
                groups_without_tariff = 3
                if len(match.groups()) == groups_with_tariff:
                    # Паттерн: название + volume + unit + tariff
                    volume = Decimal(match.group(2))
                    unit = match.group(3).strip()
                    return {"volume": volume, "unit": unit}
                elif len(match.groups()) == groups_without_tariff:
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
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не название услуги
    if any(keyword in service_name.upper() for keyword in exclude_keywords):
        return None

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

    # Удаляем лишние пробелы
    line = " ".join(line.split())

    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не услуга
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return None

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
                result["service_name"] = clean_service_name(str(result["service_name"]))

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

                # Попробуем извлечь тариф из названия
                extracted_tariff = extract_tariff_from_name(d["service_name"].strip())
                if extracted_tariff:
                    result["tariff"] = extracted_tariff

                # Очищаем название услуги от числовых данных
                result["service_name"] = clean_service_name(str(result["service_name"]))

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
                result["service_name"] = clean_service_name(str(result["service_name"]))

                return result
        except (ValueError, TypeError):
            pass

    return None


def parse_services(text_content: str) -> list:
    """
    Parse services from EPD document table with support for multi-line service names.
    Универсальный парсер, который работает с разными форматами таблиц.

    Args:
        text_content: Extracted text from PDF

    Returns:
        List of dictionaries with service data
    """
    services = []
    lines = text_content.split("\n")

    # Состояние парсера
    in_services_section = False
    current_service_name = ""
    current_service_data = None

    # Счетчик для отслеживания порядка услуг
    service_order = 1

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # Определяем начало секции услуг
        if any(
            keyword in stripped_line.upper()
            for keyword in [
                "РАСЧЕТ РАЗМЕРА ПЛАТЫ",
                "Начисления за",
                "ВИДЫ УСЛУГ",
                "УСЛУГА",
            ]
        ):
            in_services_section = True
            continue

        # Проверяем, содержит ли строка название услуги или является строкой с данными
        if in_services_section:
            if contains_service_data(stripped_line):
                # Если у нас есть сохраненное название и данные, сохраняем предыдущую услугу
                if current_service_name and current_service_data:
                    current_service_data["service_name"] = current_service_name
                    current_service_data["order"] = str(service_order)
                    services.append(current_service_data)
                    service_order += 1
                    current_service_data = None

                # Парсим как однострочную услугу
                service_data = parse_universal_service_line(stripped_line)
                if service_data:
                    service_data["order"] = str(service_order)
                    services.append(service_data)
                    service_order += 1
                else:
                    # Если не удалось распарсить, пробуем как многострочную услугу
                    current_service_data = parse_multiline_service(stripped_line)
                    if not current_service_data:
                        # Если и это не удалось, сохраняем название для следующей строки
                        current_service_name = stripped_line
            elif is_service_name_line(stripped_line):
                # Сохраняем предыдущую услугу, если есть
                if current_service_name and current_service_data:
                    current_service_data["service_name"] = current_service_name
                    current_service_data["order"] = str(service_order)
                    services.append(current_service_data)
                    service_order += 1
                    current_service_data = None

                # Сохраняем название для следующей строки
                current_service_name = stripped_line

        # Определяем конец секции услуг
        if in_services_section and any(
            keyword in stripped_line.upper()
            for keyword in [
                "Всего за",
                "Итого к оплате",
                "ИТОГО:",
                "Сведения о перерасчетах",
                "СПРАВОЧНАЯ ИНФОРМАЦИЯ",
            ]
        ):
            break

    # Сохраняем последнюю услугу, если она есть
    if current_service_name and current_service_data is not None:
        current_service_data["service_name"] = current_service_name
        current_service_data["order"] = str(service_order)
        services.append(current_service_data)

    return services


def parse_universal_service_line(line: str) -> dict[str, str | Decimal | None] | None:
    """
    Универсальный парсер строки услуги, который обрабатывает все возможные форматы.

    Поддерживаемые форматы:
    1. [название] [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    2. [название] [объем] [ед.изм.] [начислено] [перерасчет] [долг] [оплачено] [итого]
    3. [название] [начислено] [перерасчет] [долг] [оплачено] [итого]
    4. [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    """

    # Удаляем лишние пробелы
    line = " ".join(line.split())

    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не услуга
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return None

    def normalize_number(num_str: str) -> str:
        return num_str.replace(" ", "").replace(",", ".")

    def safe_decimal(value: str) -> Decimal | None:
        try:
            normalized = normalize_number(value)
            # Убираем лишние пробелы и проверяем на пустую строку
            normalized = normalized.strip()
            if not normalized:
                return None
            return Decimal(normalized)
        except (ValueError, InvalidOperation):
            return None

    # Паттерн 1: Полный формат с названием и всеми данными
    # [название] [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern1 = (
        r"^(?P<service_name>.+?)\s+"
        r"(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern1, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги
            service_name = clean_service_name(d["service_name"].strip())
            # Если название содержит только числовые данные, определяем по контексту
            if re.match(r"^[\d.]+\s+[^\d\s]+\.?$", service_name):
                if volume and unit and tariff:
                    service_name = determine_service_name_by_context(
                        volume, unit, tariff, amount or Decimal("0")
                    )

            result = {
                "service_name": service_name,
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            # Проверяем, что все обязательные поля заполнены
            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 2: Формат без тарифа
    # [название] [объем] [ед.изм.] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern2 = (
        r"^(?P<service_name>.+?)\s+"
        r"(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern2, line)
    if match:
        try:
            d = match.groupdict()
            result = {
                "service_name": clean_service_name(d["service_name"].strip()),
                "volume": safe_decimal(d["volume"]),
                "unit": d["unit"].strip(),
                "tariff": None,
                "amount": safe_decimal(d["amount"]),
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            # Попробуем извлечь тариф из названия
            extracted_tariff = extract_tariff_from_name(d["service_name"].strip())
            if extracted_tariff:
                result["tariff"] = extracted_tariff

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 3: Только суммы без объема и тарифа (но НЕ для строк, начинающихся с volume + unit)
    # [название] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern3 = (
        r"^(?P<service_name>(?![\d.]+\s+[^\d\s]+\.?\s+)[^0-9].+?)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern3, line)
    if match:
        try:
            d = match.groupdict()
            result = {
                "service_name": clean_service_name(d["service_name"].strip()),
                "volume": None,
                "unit": None,
                "tariff": None,
                "amount": safe_decimal(d["amount"]),
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            # Попробуем извлечь volume, unit и tariff из названия
            volume_unit = extract_volume_unit_from_name(d["service_name"].strip())
            if volume_unit:
                result["volume"] = volume_unit["volume"]
                result["unit"] = volume_unit["unit"]

            extracted_tariff = extract_tariff_from_name(d["service_name"].strip())
            if extracted_tariff:
                result["tariff"] = extracted_tariff

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 4: Только данные без названия (для многострочных услуг)
    # [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern4 = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    # Паттерн 4a: Строки типа "56.50 кв.м. 22.00 1 243,00 0,00 1 017,00 1 017,00 1 243,00"
    # [объем] [ед.изм.] [тариф] [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern4a = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    # Паттерн 4b: Строки типа "56.50 кв.м. 22.00 1 243,00 0,00 1 017,00 1 017,00 1 243,00"
    # где первое число - это volume, второе - tariff, а не начислено
    pattern4b = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    # Паттерн 4c: Строки типа "56.50 кв.м. 22.00 1 243,00 0,00 1 017,00 1 017,00 1 243,00"
    # где volume и unit находятся в начале, а tariff - это второе число
    pattern4c = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    # Паттерн 4d: Специальный паттерн для строк типа "56.50 кв.м. 22.00 1 243,00 0,00 1 017,00 1 017,00 1 243,00"
    # где первые два числа - это volume и tariff, а остальные - данные
    pattern4d = (
        r"^(?P<volume>[\d.]+)\s+"
        r"(?P<unit>[^\d\s]+\.?)\s+"
        r"(?P<tariff>[\d.]+)\s+"
        r"(?P<amount>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<recalculation>-?[\d\s,]+[.,]\d{2})\s+"
        r"(?P<debt>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<paid>[\d\s,]+[.,]\d{2})\s+"
        r"(?P<total>[\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern4, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги по контексту
            service_name_1: str | None = None
            if volume and unit and tariff:
                service_name_1 = determine_service_name_by_context(
                    volume, unit, tariff, amount or Decimal("0")
                )

            result = {
                "service_name": service_name_1,  # Будет добавлено в parse_services
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Проверяем паттерн 4a
    match = re.match(pattern4a, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги по контексту
            service_name_8: str | None = None
            if volume and unit and tariff:
                service_name_8 = determine_service_name_by_context(
                    volume, unit, tariff, amount or Decimal("0")
                )

            result = {
                "service_name": service_name_8,
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Проверяем паттерн 4b (для строк с volume + unit + tariff + данные)
    match = re.match(pattern4b, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги по контексту
            service_name_9: str | None = None
            if volume and unit and tariff:
                service_name_9 = determine_service_name_by_context(
                    volume, unit, tariff, amount or Decimal("0")
                )

            result = {
                "service_name": service_name_9,
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Проверяем паттерн 4c (для строк с volume + unit + tariff + данные)
    match = re.match(pattern4c, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги по контексту
            service_name_6: str | None = None
            if volume and unit and tariff:
                service_name_6 = determine_service_name_by_context(
                    volume, unit, tariff, amount or Decimal("0")
                )

            result = {
                "service_name": service_name_6,
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Проверяем паттерн 4d (специальный паттерн для строк с volume + unit + tariff + данные)
    match = re.match(pattern4d, line)
    if match:
        try:
            d = match.groupdict()
            volume = safe_decimal(d["volume"])
            unit = d["unit"].strip()
            tariff = safe_decimal(d["tariff"])
            amount = safe_decimal(d["amount"])

            # Определяем название услуги по контексту
            service_name_7: str | None = None
            if volume and unit and tariff:
                service_name_7 = determine_service_name_by_context(
                    volume, unit, tariff, amount or Decimal("0")
                )

            result = {
                "service_name": service_name_7,
                "volume": volume,
                "unit": unit,
                "tariff": tariff,
                "amount": amount,
                "recalculation": safe_decimal(d["recalculation"]),
                "debt": safe_decimal(d["debt"]),
                "paid": safe_decimal(d["paid"]),
                "total": safe_decimal(d["total"]),
            }

            if all(v is not None for v in [result["amount"], result["total"]]):
                return result
        except (ValueError, TypeError):
            pass

    # Паттерн 5: Только числа (5 чисел подряд)
    # [начислено] [перерасчет] [долг] [оплачено] [итого]
    pattern5 = (
        r"^([\d\s,]+[.,]\d{2})\s+"
        r"(-?[\d\s,]+[.,]\d{2})\s+"
        r"([\d\s,]+[.,]\d{2})\s+"
        r"([\d\s,]+[.,]\d{2})\s+"
        r"([\d\s,]+[.,]\d{2})$"
    )

    match = re.match(pattern5, line)
    if match:
        try:
            numbers = [safe_decimal(match.group(i)) for i in range(1, 6)]
            if all(num is not None for num in numbers):
                result = {
                    "service_name": None,  # Будет добавлено в parse_services
                    "volume": None,
                    "unit": None,
                    "tariff": None,
                    "amount": numbers[0],
                    "recalculation": numbers[1],
                    "debt": numbers[2],
                    "paid": numbers[3],
                    "total": numbers[4],
                }
                return result
        except (ValueError, TypeError):
            pass

    return None


def is_service_data_line(line: str) -> bool:
    """
    Проверяет, является ли строка данными услуги (содержит числа в конце).
    """
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не данные услуги
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return False

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
        "ВЗНОС",
        "КАПИТАЛЬНЫЙ",
        "ЖИЛОГО",
        "ПОМЕЩЕНИЯ",
        "ОДН",
        "В/С",
        "ТКО",
        "ВКГО",
        "ЗАПИРАЮЩЕЕ",
        "УСТРОЙСТВО",
        "ЭНЕРГИЯ",
        "НОСИТЕЛЬ",
        "ВОДА",
        "ВОДОСНАБЖЕНИЕ",
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
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не название услуги
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return False

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
        "ВЗНОС",
        "КАПИТАЛЬНЫЙ",
        "ЖИЛОГО",
        "ПОМЕЩЕНИЯ",
        "ОДН",
        "В/С",
        "ТКО",
        "ВКГО",
        "ЗАПИРАЮЩЕЕ",
        "УСТРОЙСТВО",
        "ЭНЕРГИЯ",
        "НОСИТЕЛЬ",
        "ВОДА",
        "ВОДОСНАБЖЕНИЕ",
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
        "Всего за",
        "Без учета добровольного",
        "С учетом добровольного",
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
    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не данные услуги
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return False

    # Ищем числа в формате: цифры + пробелы + запятая/точка + 2 цифры
    return bool(re.search(r"[\d\s,]+[.,]\d{2}", line))


def parse_multiline_service(line: str) -> dict[str, str | Decimal | None] | None:
    """
    Специальный парсер для многострочных услуг типа:
    "68.90 кв.м. 22.00 1 515,80 0,00 1 240,20 1 240,20 1 515,80"
    """

    # Удаляем лишние пробелы
    line = " ".join(line.split())

    # Исключаем строки "Всего за июль" и подобные
    exclude_keywords = [
        "ВСЕГО ЗА ИЮЛЬ",
        "ВСЕГО ЗА",
        "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
        "С УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ",
    ]

    # Если строка содержит исключающие ключевые слова, то это не услуга
    if any(keyword in line.upper() for keyword in exclude_keywords):
        return None

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


def parse_epd_pdf(pdf_file: Any) -> dict[str, Any]:
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
        ) from e
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info("Temporary file cleaned up")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")


def create_epd_document_from_parsed_data(
    parsed_data: dict[str, Any],
) -> Any:  # Using Any instead of "EpdDocument" to avoid circular imports
    """
    Create EpdDocument instance from parsed data.

    Args:
        parsed_data: Dictionary with parsed EPD data

    Returns:
        EpdDocument instance (not saved to database)
    """

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

    # Note: Don't save here - let the calling code handle saving
    # This allows for transaction management and validation

    return document


def save_epd_document_with_related_data(
    parsed_data: dict[str, Any],
    form_data: dict[str, Any] | None = None,
) -> Any:  # Using Any instead of "EpdDocument" to avoid circular imports
    """
    Save EpdDocument and all related data to database.

    Args:
        parsed_data: Dictionary with parsed EPD data
        form_data: Optional form data to override parsed data

    Returns:
        Saved EpdDocument instance
    """

    logger.info("Saving EPD document with related data to database")

    with transaction.atomic():
        # Use form data if provided, otherwise use parsed data
        data_to_use = form_data if form_data is not None else parsed_data

        # Create and save main document
        document = create_epd_document_from_parsed_data(data_to_use)
        document.save()

        # Save service charges
        for service_data in parsed_data.get("services", []):
            # Обрабатываем None значения, заменяя их на 0.00
            volume = service_data.get("volume")
            if volume is None:
                volume = Decimal("0.00")

            tariff = service_data.get("tariff")
            if tariff is None:
                tariff = Decimal("0.00")

            amount = service_data.get("amount")
            if amount is None:
                amount = Decimal("0.00")

            recalculation = service_data.get("recalculation")
            if recalculation is None:
                recalculation = Decimal("0.00")

            debt = service_data.get("debt")
            if debt is None:
                debt = Decimal("0.00")

            paid = service_data.get("paid")
            if paid is None:
                paid = Decimal("0.00")

            total = service_data.get("total")
            if total is None:
                total = Decimal("0.00")

            # Используем порядок из парсера или создаем новый
            order = service_data.get("order")
            if order is None:
                order = len(parsed_data.get("services", [])) + 1
            else:
                try:
                    order = int(order)
                except (ValueError, TypeError):
                    order = len(parsed_data.get("services", [])) + 1

            # Ограничиваем длину единиц измерений
            max_unit_length = 20
            unit = service_data.get("unit", "")
            if len(unit) > max_unit_length:
                logger.warning(
                    f"Unit '{unit}' truncated to 20 characters for service '{service_data['service_name']}'"
                )
                unit = unit[:20]

            service_charge = ServiceCharge(
                document=document,
                service_name=service_data["service_name"],
                volume=volume,
                unit=unit,
                tariff=tariff,
                amount=amount,
                recalculation=recalculation,
                debt=debt,
                paid=paid,
                total=total,
                order=order,
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

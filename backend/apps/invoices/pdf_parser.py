"""
Парсер российских квитанций ЖКХ (ЕПД — Единый Платёжный Документ)
через pdfplumber. Извлекает структурированные данные из PDF.
"""

import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)

RUSSIAN_MONTHS: dict[str, int] = {
    "январь": 1, "января": 1, "январе": 1,
    "февраль": 2, "февраля": 2, "феврале": 2,
    "март": 3, "марта": 3, "марте": 3,
    "апрель": 4, "апреля": 4, "апреле": 4,
    "май": 5, "мая": 5, "мае": 5,
    "июнь": 6, "июня": 6, "июне": 6,
    "июль": 7, "июля": 7, "июле": 7,
    "август": 8, "августа": 8, "августе": 8,
    "сентябрь": 9, "сентября": 9, "сентябре": 9,
    "октябрь": 10, "октября": 10, "октябре": 10,
    "ноябрь": 11, "ноября": 11, "ноябре": 11,
    "декабрь": 12, "декабря": 12, "декабре": 12,
}

# Строки-заголовки секций — пропускаются
SECTION_HEADERS = {
    "начисления за жилищные услуги",
    "начисления за коммунальные услуги",
    "начисления за иные услуги",
}

# Однострочная строка услуги:
# SERVICE_NAME QUANTITY UNIT TARIFF AMOUNT_CHARGED DEBT PAID TOTAL
_SINGLE_LINE_RE = re.compile(
    r'^(?P<service>[А-ЯЁа-яё][А-ЯЁа-яё\s/().]+?)'
    r'\s+(?P<quantity>\d+(?:\.\d+)?)'
    r'\s+(?P<unit>[А-Яа-яЁё][А-Яа-яЁё./ ]*?\.?)'
    r'\s+(?P<tariff>\d+(?:\.\d+)?)'
    r'\s+(?P<charged>-?[\d\s]+,\d{2})'
    r'\s+(?P<debt>-?[\d\s]+,\d{2})'
    r'\s+(?P<paid>-?[\d\s]+,\d{2})'
    r'\s+(?P<total>-?[\d\s]+,\d{2})$',
)

# Числовая строка-продолжение (когда service name на предыдущей строке):
# QUANTITY UNIT TARIFF AMOUNT_CHARGED DEBT PAID TOTAL
_CONTINUATION_RE = re.compile(
    r'^(?P<quantity>\d+(?:\.\d+)?)'
    r'\s+(?P<unit>[А-Яа-яЁё][А-Яа-яЁё./ ]*?\.?)'
    r'\s+(?P<tariff>\d+(?:\.\d+)?)'
    r'\s+(?P<charged>-?[\d\s]+,\d{2})'
    r'\s+(?P<debt>-?[\d\s]+,\d{2})'
    r'\s+(?P<paid>-?[\d\s]+,\d{2})'
    r'\s+(?P<total>-?[\d\s]+,\d{2})$',
)

# Строка "Всего за ... :" с итогами
_SUMMARY_RE = re.compile(
    r'^(?P<label>Всего за .+?:)\s+'
    r'(?P<charged>-?[\d\s]+,\d{2})\s+'
    r'(?P<debt>-?[\d\s]+,\d{2})\s+'
    r'(?P<paid>-?[\d\s]+,\d{2})\s+'
    r'(?P<total>-?[\d\s]+,\d{2})$',
    re.MULTILINE,
)

# "Итого к оплате за ... : AMOUNT"
_ITOGO_RE = re.compile(
    r'^Итого к оплате за .+?:\s+(?P<amount>[\d\s]+,\d{2})$',
    re.MULTILINE,
)


def parse_russian_number(text: str | None) -> Decimal | None:
    """Парсит число в русском формате: '1 243,00' → Decimal('1243.00')."""
    if not text:
        return None
    text = text.strip()
    if not text or text == "-":
        return None
    cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    cleaned = cleaned.rstrip(".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _extract_period(text: str) -> dict[str, Any]:
    """Извлекает период: 'за январь 2026 г.' → month=1, year=2026."""
    result: dict[str, Any] = {
        "start_date": None, "end_date": None, "month": None, "year": None,
    }
    match = re.search(r"за\s+(\w+)\s+(\d{4})\s*г?\.?", text.lower())
    if not match:
        return result
    month = RUSSIAN_MONTHS.get(match.group(1))
    year = int(match.group(2))
    if not month:
        return result
    result["month"] = month
    result["year"] = year
    result["start_date"] = date(year, month, 1).isoformat()
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    result["end_date"] = (next_month - timedelta(days=1)).isoformat()
    return result


def _extract_account_number(text: str) -> str | None:
    """Извлекает лицевой счёт: '8 1 9 6 7 - 6 4 2' → '81967642'."""
    match = re.search(r"[Лл]ицевой\s+сч[её]т[:\s]*([0-9\s\-]+)", text)
    if not match:
        return None
    cleaned = re.sub(r"[\s\-]", "", match.group(1)).strip()
    return cleaned or None


def _extract_payer_name(text: str) -> str | None:
    """Извлекает ФИО плательщика."""
    match = re.search(r"ФИО[:\s]+(.+)", text)
    return match.group(1).strip() if match else None


def _extract_address(text: str) -> str | None:
    """Извлекает адрес."""
    match = re.search(r"Адрес[:\s]+(.+)", text)
    return match.group(1).strip() if match else None


def _extract_provider_name(text: str) -> str | None:
    """Извлекает название управляющей организации."""
    # Ищем организационную форму + всё в кавычках до 6-значного почтового индекса
    match = re.search(
        r'УПРАВЛЯЮЩАЯ\s+ОРГАНИЗАЦИЯ[:\s]*'
        r'((?:ООО|ОАО|ЗАО|ПАО|ТСЖ|ГУП|МУП|АО)\s*[«"].+?[»"])(?=\d{6})',
        text,
    )
    return match.group(1).strip() if match else None


def _extract_header_totals(text: str) -> dict[str, Decimal | None]:
    """Извлекает итоги из шапки: 'X руб. Y коп.'."""
    totals: dict[str, Decimal | None] = {
        "amount_due_with_insurance": None,
        "amount_due_without_insurance": None,
    }
    rub_kop = r"(\d[\d\s]*)\s*руб\.\s*(\d{1,2})\s*коп\."
    all_matches = re.findall(rub_kop, text)
    if len(all_matches) >= 2:
        rub1 = all_matches[0][0].replace(" ", "")
        totals["amount_due_with_insurance"] = Decimal(f"{rub1}.{all_matches[0][1]}")
        rub2 = all_matches[1][0].replace(" ", "")
        totals["amount_due_without_insurance"] = Decimal(f"{rub2}.{all_matches[1][1]}")
    elif len(all_matches) == 1:
        rub = all_matches[0][0].replace(" ", "")
        totals["amount_due_without_insurance"] = Decimal(f"{rub}.{all_matches[0][1]}")
    return totals


def _make_item(service: str, m_dict: dict[str, str]) -> dict[str, Any]:
    """Создаёт dict line_item из названия услуги и regex-групп."""
    return {
        "service_name": service,
        "unit": m_dict["unit"].strip(),
        "quantity": Decimal(m_dict["quantity"]),
        "tariff": Decimal(m_dict["tariff"]),
        "amount_charged": parse_russian_number(m_dict["charged"]),
        "recalculation": None,
        "debt": parse_russian_number(m_dict["debt"]),
        "amount": parse_russian_number(m_dict["total"]),
        "provider": None,
        "meter_id": None,
        "previous_reading": None,
        "current_reading": None,
    }


def _parse_line_items_from_text(text: str) -> list[dict[str, Any]]:
    """
    Парсит строки услуг из текста PDF.

    Обрабатывает два формата:
    1. Однострочный: SERVICE QUANTITY UNIT TARIFF CHARGED DEBT PAID TOTAL
    2. Двухстрочный: SERVICE (строка 1) + QUANTITY UNIT TARIFF CHARGED DEBT PAID TOTAL (строка 2)
    """
    items: list[dict[str, Any]] = []
    lines = text.split("\n")
    pending_service: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            pending_service = None
            continue

        # Пропускаем заголовки секций
        if stripped.lower() in SECTION_HEADERS:
            pending_service = None
            continue

        # Пропускаем итоговые строки
        lower = stripped.lower()
        if lower.startswith("всего") or lower.startswith("итого"):
            pending_service = None
            continue

        # Пробуем однострочный формат
        m = _SINGLE_LINE_RE.match(stripped)
        if m:
            service = m.group("service").strip()
            if service.lower() not in SECTION_HEADERS:
                items.append(_make_item(service, m.groupdict()))
            pending_service = None
            continue

        # Пробуем числовую строку-продолжение (данные для предыдущего service name)
        if pending_service:
            m = _CONTINUATION_RE.match(stripped)
            if m:
                items.append(_make_item(pending_service, m.groupdict()))
                pending_service = None
                continue

        # Строка только с кириллическим текстом — потенциальное название услуги
        # (для двухстрочного формата: ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ / СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ)
        if re.match(r'^[А-ЯЁ][А-ЯЁа-яё\s/().]+$', stripped) and len(stripped) > 3:
            pending_service = stripped
            continue

        pending_service = None

    return items


def _parse_summary_totals(text: str) -> dict[str, Any]:
    """Извлекает итоги из строк 'Всего за ...' и 'Итого к оплате'."""
    totals: dict[str, Any] = {
        "amount_due": None,
        "amount_due_without_insurance": None,
        "amount_due_with_insurance": None,
        "amount_charged": None,
        "amount_paid": None,
        "amount_recalculation": None,
        "currency": "RUB",
    }

    for m in _SUMMARY_RE.finditer(text):
        label = m.group("label").lower()
        charged = parse_russian_number(m.group("charged"))
        debt = parse_russian_number(m.group("debt"))
        paid = parse_russian_number(m.group("paid"))
        total = parse_russian_number(m.group("total"))

        is_without = "без" in label and "страхован" in label
        is_with = "с учет" in label and "страхован" in label and "без" not in label

        if is_without:
            totals["amount_due_without_insurance"] = total
            totals["amount_charged"] = charged
            totals["amount_recalculation"] = debt
            totals["amount_paid"] = paid
        elif is_with:
            totals["amount_due_with_insurance"] = total

    for m in _ITOGO_RE.finditer(text):
        full_match = m.group(0).lower()
        amount = parse_russian_number(m.group("amount"))
        if "без" in full_match and "страхован" in full_match:
            totals["amount_due_without_insurance"] = amount
        elif "с учет" in full_match and "страхован" in full_match:
            totals["amount_due_with_insurance"] = amount

    totals["amount_due"] = (
        totals["amount_due_without_insurance"]
        or totals["amount_due_with_insurance"]
    )
    return totals


# Паттерн строки ИПУ из текста: SERVICE ИПУ METER_ID DATE PREV CURR ...
# ГОРЯЧЕЕ В/С (НОСИТЕЛЬ) ИПУ 230575136 24.04.2030 38.000000 39.000000 ...
# service_name ограничен одной строкой (нет переносов)
_METER_IPU_RE = re.compile(
    r'^(?P<service>[А-ЯЁ][А-ЯЁа-яё /().]+?)'
    r'[ \t]+ИПУ'
    r'[ \t]+(?P<meter_id>\d{6,})'
    r'[ \t]+\d{2}\.\d{2}\.\d{4}'   # дата поверки
    r'[ \t]+(?P<prev>\d+\.\d+)'
    r'[ \t]+(?P<curr>\d+\.\d+)',
    re.MULTILINE,
)


def _split_last_col_pair(col6: str | None, col7: str | None) -> tuple[str | None, str | None]:
    """
    В 8-колоночном PDF колонки «Оплачено» и «ИТОГО» слипаются:
    col[6]='2,9'  col[7]='6 81,59'  → paid='2,96', total='81,59'
    Восстанавливаем: к col[6] прибавляем первый «кусочек» col[7].
    """
    if col7 is None:
        return col6, None
    parts = (col7 or "").strip().split(None, 1)
    paid = ((col6 or "").strip() + parts[0]) if parts else col6
    total = parts[1] if len(parts) > 1 else None
    return paid or None, total or None


def _parse_qty_unit_tariff(col1: str | None, col2: str | None) -> tuple[str, str, str]:
    """
    Извлекает quantity, unit, tariff из двух ячеек, которые могут быть разбиты
    произвольно (пример: '0.621551 к' + 'уб.м. 40.73').
    Возвращает (quantity_str, unit_str, tariff_str) или пустые строки при неудаче.
    """
    combined = ((col1 or "") + (col2 or "")).strip()
    # quantity: первое число (целое или дробное с . или ,)
    m = re.match(r"^(\d+[\d.,]*)\s*(.+)", combined)
    if not m:
        return "", "", ""
    qty = m.group(1).replace(",", ".")
    rest = m.group(2).strip()
    # tariff: последнее число в rest
    tm = re.search(r"(\d+[\d.,]*)\s*$", rest)
    if not tm:
        return qty, rest, ""
    tariff = tm.group(1).replace(",", ".")
    unit = rest[: tm.start()].strip()
    return qty, unit, tariff


def _billing_table_to_items(table: list[list[str | None]]) -> list[dict[str, Any]]:
    """
    Парсит основную таблицу начислений из pdfplumber в list[line_item].
    Поддерживает два формата:
      • 5 колонок (без перерасчётов): SERVICE+QTY | QTY+UNIT+TARIFF | CHARGED | DEBT+PAID | TOTAL
      • 8 колонок (с перерасчётами): SERVICE | QTY | UNIT+TARIFF | CHARGED | REcalc | DEBT | PAID | TOTAL
    """
    if not table or len(table) < 2:
        return []

    # Определяем формат по числу колонок в строке данных (пропускаем заголовки)
    ncols = max(len(row) for row in table)

    items: list[dict[str, Any]] = []
    skip_words = SECTION_HEADERS | {"виды услуг"}

    for row in table:
        if not row or not row[0]:
            continue
        service_raw = (row[0] or "").strip()
        if not service_raw:
            continue

        lower = service_raw.lower()
        # Пропускаем заголовки секций, итоговые строки и строки заголовка таблицы
        if lower in skip_words or lower.startswith("всего") or lower.startswith("итого"):
            continue
        if "расчет размера" in lower or "жилищно-коммунальн" in lower:
            continue
        if "начисления за" in lower:
            continue

        if ncols >= 7:
            # === 8-колоночный формат (февраль) ===
            col1 = row[1] if len(row) > 1 else None
            col2 = row[2] if len(row) > 2 else None
            charged_raw = (row[3] or "").strip() if len(row) > 3 else None
            rekalc_raw = (row[4] or "").strip() if len(row) > 4 else None
            debt_raw = (row[5] or "").strip() if len(row) > 5 else None
            col6 = row[6] if len(row) > 6 else None
            col7 = row[7] if len(row) > 7 else None

            paid_raw, total_raw = _split_last_col_pair(col6, col7)
            qty_str, unit_str, tariff_str = _parse_qty_unit_tariff(col1, col2)

            service_name = service_raw.replace("\n", " ").strip()
            # Убираем суффикс "_" (артефакт PDF)
            service_name = service_name.rstrip("_").strip()

        else:
            # === 5-колоночный формат (январь) ===
            # col[0]: "SERVICE\nQTY_part1" или "SERVICE QTY_part1"
            # col[1]: "QTY_part2 UNIT TARIFF"
            col1 = row[1] if len(row) > 1 else None
            charged_raw = (row[2] or "").strip() if len(row) > 2 else None
            col3 = row[3] if len(row) > 3 else None
            total_raw = (row[4] or "").strip() if len(row) > 4 else None

            rekalc_raw = None

            # Разделяем col[3] = "DEBT PAID"
            debt_raw = None
            paid_raw = None
            if col3:
                nums = re.findall(r"-?[\d\s]+,\d{2}", col3)
                if len(nums) >= 2:
                    debt_raw = nums[0].strip()
                    paid_raw = nums[1].strip()
                elif len(nums) == 1:
                    debt_raw = nums[0].strip()

            # Извлекаем service_name и qty_part1 из col[0]
            # Пример: "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ\n56.5" или "ГАЗОСНАБЖЕНИЕ 2"
            col0_parts = re.split(r"\n", service_raw, maxsplit=1)
            if len(col0_parts) == 2:
                service_name = col0_parts[0].strip()
                qty_part1 = col0_parts[1].strip()
            else:
                # Ищем число в конце строки (количество)
                m_qty = re.search(r"^(.+?)\s+(\d[\d.]*)\s*$", service_raw)
                if m_qty:
                    service_name = m_qty.group(1).strip()
                    qty_part1 = m_qty.group(2).strip()
                else:
                    service_name = service_raw
                    qty_part1 = ""

            qty_str, unit_str, tariff_str = _parse_qty_unit_tariff(qty_part1, col1)

        # Пропускаем строки без числовых данных
        if not charged_raw and not total_raw:
            continue

        # Пропускаем артефакты заголовков (нет ни одного числа в данных)
        charged_val = parse_russian_number(charged_raw)
        total_val = parse_russian_number(total_raw)
        if charged_val is None and total_val is None:
            continue

        try:
            qty = Decimal(qty_str) if qty_str else None
            tariff = Decimal(tariff_str.replace(",", ".")) if tariff_str else None
        except (InvalidOperation, ValueError):
            qty = tariff = None

        items.append({
            "service_name": service_name,
            "unit": unit_str,
            "quantity": qty,
            "tariff": tariff,
            "amount_charged": parse_russian_number(charged_raw),
            "recalculation": parse_russian_number(rekalc_raw),
            "debt": parse_russian_number(debt_raw),
            "amount": parse_russian_number(total_raw),
            "provider": None,
            "meter_id": None,
            "previous_reading": None,
            "current_reading": None,
        })

    return items


def _parse_line_items_from_tables(tables: list[list[list[str | None]]]) -> list[dict[str, Any]]:
    """
    Находит основную таблицу начислений среди всех таблиц страницы и парсит её.
    Основная таблица содержит колонку «Начислено по тарифу» или «ИТОГО».
    """
    for table in tables:
        if not table or len(table) < 3:
            continue
        # Ищем по заголовку — строка должна содержать «расчет» и «услуги»
        header_text = " ".join((cell or "") for cell in (table[0] or [])).lower()
        if "расчет" in header_text and ("услуги" in header_text or "жилищно" in header_text):
            items = _billing_table_to_items(table)
            if items:
                return items
    return []


def _parse_summary_from_table(table: list[list[str | None]], ncols: int) -> dict[str, Any] | None:
    """Извлекает итоговые суммы из строк «Всего за ...» внутри таблицы начислений."""
    totals: dict[str, Any] = {}
    for row in table:
        if not row or not row[0]:
            continue
        label = (row[0] or "").strip().lower()
        if not label.startswith("всего"):
            continue

        is_without = "без" in label and "страхован" in label
        is_with = "с учет" in label and "страхован" in label and "без" not in label

        if ncols >= 7:
            charged = parse_russian_number((row[3] or "").strip() if len(row) > 3 else None)
            rekalc = parse_russian_number((row[4] or "").strip() if len(row) > 4 else None)
            debt = parse_russian_number((row[5] or "").strip() if len(row) > 5 else None)
            paid_raw, total_raw = _split_last_col_pair(
                row[6] if len(row) > 6 else None,
                row[7] if len(row) > 7 else None,
            )
            paid = parse_russian_number(paid_raw)
            total = parse_russian_number(total_raw)
        else:
            charged = parse_russian_number((row[2] or "").strip() if len(row) > 2 else None)
            col3 = (row[3] or "").strip() if len(row) > 3 else ""
            total = parse_russian_number((row[4] or "").strip() if len(row) > 4 else None)
            nums = re.findall(r"-?[\d\s]+,\d{2}", col3)
            rekalc = parse_russian_number(nums[0].strip()) if nums else None
            paid = parse_russian_number(nums[1].strip()) if len(nums) > 1 else None
            debt = None

        if is_without:
            totals["amount_charged"] = charged
            totals["amount_recalculation"] = rekalc
            totals["amount_paid"] = paid
            totals["amount_due_without_insurance"] = total
        elif is_with:
            totals["amount_due_with_insurance"] = total

    return totals or None


def _parse_merge_totals_from_tables(
    tables: list[list[list[str | None]]],
    result_totals: dict[str, Any],
) -> None:
    """Извлекает итоги из основной таблицы начислений и обновляет result_totals."""
    for table in tables:
        if not table or len(table) < 3:
            continue
        header_text = " ".join((cell or "") for cell in (table[0] or [])).lower()
        if "расчет" in header_text and ("услуги" in header_text or "жилищно" in header_text):
            ncols = max(len(row) for row in table)
            summary = _parse_summary_from_table(table, ncols)
            if summary:
                for k, v in summary.items():
                    if v is not None:
                        result_totals[k] = v
            return


def _parse_meter_readings_from_tables(tables: list[list[list[str | None]]]) -> dict[str, dict]:
    """Парсит счётчики из pdfplumber-таблиц (работает когда PDF содержит линии таблицы)."""
    readings: dict[str, dict] = {}

    meter_table = None
    for table in tables:
        if not table or len(table) < 2:
            continue
        header_text = " ".join((cell or "") for cell in table[0]).lower()
        if "справочн" in header_text or "показани" in header_text:
            meter_table = table
            break

    if not meter_table:
        return readings

    # Определяем формат по числу колонок
    ncols_meter = max((len(row) for row in meter_table), default=0)

    for row in meter_table[1:]:
        if len(row) < 4:
            continue
        service = (row[0] or "").strip()
        if not service or service.lower() in ("виды услуг", "справочная информация"):
            continue
        if not re.search(r"[А-ЯЁа-яё]", service):
            continue

        meter_type = (row[1] or "").strip() if len(row) > 1 else ""
        if meter_type != "ИПУ":
            continue

        meter_id = (row[2] or "").strip() if len(row) > 2 else None
        if meter_id and not re.match(r"^\d+$", meter_id):
            meter_id = None

        if ncols_meter >= 10:
            # Новый формат (11 кол.): col[4]=предыдущее, col[5]=текущее
            prev_str = (row[4] or "").strip() if len(row) > 4 else ""
            curr_str = (row[5] or "").strip() if len(row) > 5 else ""
            nums_prev = re.findall(r"(\d+(?:\.\d+)?)", prev_str)
            nums_curr = re.findall(r"(\d+(?:\.\d+)?)", curr_str)
            prev_reading = Decimal(nums_prev[0]) if nums_prev else None
            curr_reading = Decimal(nums_curr[0]) if nums_curr else None
        else:
            # Старый формат (9 кол.): col[3]="дата предыдущее", col[4]="текущее объём"
            col3 = (row[3] or "").strip() if len(row) > 3 else ""
            col4 = (row[4] or "").strip() if len(row) > 4 else ""
            nums3 = re.findall(r"(\d+\.\d+)", col3)
            prev_reading = Decimal(nums3[-1]) if nums3 else None
            nums4 = re.findall(r"(\d+\.\d+)", col4)
            curr_reading = Decimal(nums4[0]) if nums4 else None

        readings[service.upper()] = {
            "meter_id": meter_id,
            "previous_reading": prev_reading,
            "current_reading": curr_reading,
        }

    return readings


def _parse_meter_readings_from_text(text: str) -> dict[str, dict]:
    """Парсит счётчики из текста PDF (fallback когда таблиц нет)."""
    readings: dict[str, dict] = {}
    # Ищем только в секции "Справочная информация"
    section_match = re.search(r"Справочная информация(.+)", text, re.DOTALL | re.IGNORECASE)
    if not section_match:
        return readings
    section = section_match.group(1)
    for m in _METER_IPU_RE.finditer(section):
        service = m.group("service").strip().upper()
        readings[service] = {
            "meter_id": m.group("meter_id"),
            "previous_reading": Decimal(m.group("prev")),
            "current_reading": Decimal(m.group("curr")),
        }
    return readings


def _parse_meter_readings(
    tables: list[list[list[str | None]]],
    full_text: str = "",
) -> dict[str, dict]:
    """
    Парсит таблицу счётчиков (Справочная информация).
    Сначала пробует извлечь из таблиц (если PDF содержит линии),
    при неудаче — из текста.
    Возвращает {SERVICE_NAME: {meter_id, previous_reading, current_reading}}.
    """
    readings = _parse_meter_readings_from_tables(tables)
    if not readings and full_text:
        readings = _parse_meter_readings_from_text(full_text)
    return readings


def _merge_meter_readings(
    line_items: list[dict[str, Any]],
    readings: dict[str, dict],
) -> None:
    """Добавляет данные счётчиков к line_items по точному совпадению названия."""
    for item in line_items:
        name_upper = item["service_name"].upper()
        if name_upper in readings:
            item.update(readings[name_upper])


def parse_epd(pdf_file) -> dict[str, Any]:
    """
    Парсит PDF файл ЕПД (Единый Платёжный Документ).

    Принимает file-like объект (Django FieldFile или открытый файл).
    Возвращает dict со структурой, совместимой с прежним ответом AI.
    """
    warnings: list[str] = []
    result: dict[str, Any] = {
        "document_type": "utility_bill",
        "provider_name": None,
        "account_number": None,
        "payer_name": None,
        "address": None,
        "period": {"start_date": None, "end_date": None, "month": None, "year": None},
        "totals": {
            "amount_due": None,
            "amount_due_without_insurance": None,
            "amount_due_with_insurance": None,
            "amount_charged": None,
            "amount_paid": None,
            "amount_recalculation": None,
            "currency": "RUB",
        },
        "line_items": [],
        "confidence": 1.0,
        "warnings": warnings,
    }

    with pdfplumber.open(pdf_file) as pdf:
        if not pdf.pages:
            warnings.append("PDF не содержит страниц")
            result["confidence"] = 0.0
            return result

        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        if not full_text.strip():
            warnings.append("Не удалось извлечь текст из PDF")
            result["confidence"] = 0.0
            return result

        # === Шапка ===
        result["provider_name"] = _extract_provider_name(full_text)
        result["account_number"] = _extract_account_number(full_text)
        result["payer_name"] = _extract_payer_name(full_text)
        result["address"] = _extract_address(full_text)
        result["period"] = _extract_period(full_text)

        # === Итоги из шапки (руб./коп.) ===
        header_totals = _extract_header_totals(full_text)

        # === Таблицы со всех страниц (нужны для line_items и счётчиков) ===
        all_tables: list[list[list[str | None]]] = []
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

        # === Строки услуг: сначала из таблиц, затем fallback на текст ===
        line_items = _parse_line_items_from_tables(all_tables)
        if not line_items:
            line_items = _parse_line_items_from_text(full_text)
        result["line_items"] = line_items

        # === Итоги: сначала из таблицы, затем fallback на текст ===
        _parse_merge_totals_from_tables(all_tables, result["totals"])

        # Дополняем итоги из текстового парсинга (для полей, которые не нашлись в таблице)
        summary_totals = _parse_summary_totals(full_text)
        for k, v in summary_totals.items():
            if v is not None and result["totals"].get(k) is None:
                result["totals"][k] = v

        # Итоги из шапки как fallback
        for key in ("amount_due_with_insurance", "amount_due_without_insurance"):
            if result["totals"][key] is None and header_totals.get(key) is not None:
                result["totals"][key] = header_totals[key]

        if result["totals"]["amount_due"] is None:
            result["totals"]["amount_due"] = (
                result["totals"]["amount_due_without_insurance"]
                or result["totals"]["amount_due_with_insurance"]
            )

        # === Счётчики из таблицы "Справочная информация" ===
        meter_readings = _parse_meter_readings(all_tables, full_text)
        _merge_meter_readings(line_items, meter_readings)

        # === Валидация / корректировка confidence ===
        if not line_items:
            warnings.append("Не найдено ни одной строки услуг")
            result["confidence"] = min(result["confidence"], 0.5)
        if not result["account_number"]:
            warnings.append("Лицевой счёт не найден")
            result["confidence"] = min(result["confidence"], 0.8)
        if not result["period"]["month"]:
            warnings.append("Период (месяц/год) не определён")
            result["confidence"] = min(result["confidence"], 0.7)

    return result

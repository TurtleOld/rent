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

from .units import normalize_unit

logger = logging.getLogger(__name__)

MAX_PAGES = 50

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

# Полная денежная сумма в русском формате: '1 000,00', '-98,30'
_FULL_AMOUNT_RE = re.compile(r"-?[\d\s]+,\d{2}")

# Суммы в хвосте строки услуги: 4 (без перерасчётов) или 5 (с колонкой
# «Перерасчёты»): начислено [перерасчёт] долг оплачено итого.
_AMOUNTS_RE = r'(?P<amounts>-?[\d\s]+,\d{2}(?:\s+-?[\d\s]+,\d{2}){3,4})'

# Однострочная строка услуги:
# SERVICE_NAME QUANTITY UNIT TARIFF SUMS
_SINGLE_LINE_RE = re.compile(
    r'^(?P<service>[А-ЯЁа-яё][А-ЯЁа-яё\s/()._]+?)'
    r'\s+(?P<quantity>\d+(?:\.\d+)?)'
    r'\s+(?P<unit>[А-Яа-яЁё][А-Яа-яЁё./ *]*?\.?)'
    r'\s+(?P<tariff>\d+(?:[.,]\d+)?)'
    r'\s+' + _AMOUNTS_RE + r'$',
)

# Числовая строка-продолжение (когда service name на предыдущей строке):
# QUANTITY UNIT TARIFF SUMS
_CONTINUATION_RE = re.compile(
    r'^(?P<quantity>\d+(?:\.\d+)?)'
    r'\s+(?P<unit>[А-Яа-яЁё][А-Яа-яЁё./ *]*?\.?)'
    r'\s+(?P<tariff>\d+(?:[.,]\d+)?)'
    r'\s+' + _AMOUNTS_RE + r'$',
)

# Строка, состоящая только из названия услуги (возможно с номером помещения).
_SERVICE_NAME_ONLY_RE = re.compile(r'^[А-ЯЁ][А-ЯЁа-яё0-9\s/()._]+$')

# Строка "Всего за ... :" с итогами
_SUMMARY_RE = re.compile(
    r'^(?P<label>Всего за .+?:)\s+' + _AMOUNTS_RE + r'$',
    re.MULTILINE,
)

# "Итого к оплате за ... : AMOUNT"
_ITOGO_RE = re.compile(
    r'^Итого к оплате за .+?:\s+(?P<amount>-?[\d\s]+,\d{2})$',
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


def _first_not_none(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    """`a or b`, но Decimal("0.00") — валидная сумма, а не «пусто»."""
    return a if a is not None else b


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
    rub_kop = r"(-?\d[\d\s]*)\s*руб\.\s*(\d{1,2})\s*коп\."
    amounts = [parse_russian_number(f"{rub},{kop:0>2}") for rub, kop in re.findall(rub_kop, text)]
    if len(amounts) >= 2:
        totals["amount_due_with_insurance"] = amounts[0]
        totals["amount_due_without_insurance"] = amounts[1]
    elif len(amounts) == 1:
        totals["amount_due_without_insurance"] = amounts[0]
    return totals


def _make_item(service: str, m_dict: dict[str, str]) -> dict[str, Any]:
    """Создаёт dict line_item из названия услуги и regex-групп.

    Args:
        service: Название услуги.
        m_dict: Группы regex с quantity, unit, tariff и amounts.

    Returns:
        Строка услуги. В хвосте может быть 5 сумм (начислено, перерасчёт,
        долг, оплачено, итого) или 4 — тогда колонки «Перерасчёты» нет.
    """
    amounts = [parse_russian_number(n) for n in _FULL_AMOUNT_RE.findall(m_dict["amounts"])]
    unit_raw = m_dict["unit"].strip()
    if len(amounts) == 5:
        charged, recalculation, debt, _paid, total = amounts
        # Формат с перерасчётами появился позже; его единицы сразу приводим
        # к канонической форме, чтобы счётчики и услуги сопоставлялись.
        unit = normalize_unit(unit_raw) or unit_raw
    else:
        charged, debt, _paid, total = amounts
        recalculation = None
        unit = unit_raw
    return {
        "service_name": service,
        "unit": unit,
        "quantity": Decimal(m_dict["quantity"]),
        "tariff": Decimal(m_dict["tariff"].replace(",", ".")),
        "amount_charged": charged,
        "recalculation": recalculation,
        "debt": debt,
        "amount": total,
        "provider": None,
        "meter_id": None,
        "previous_reading": None,
        "current_reading": None,
    }


def _clean_service_name(name: str) -> str:
    """Убирает артефакты PDF из названия услуги (подчёркивание в конце)."""
    return name.rstrip("_").strip()


def _is_service_name_line(line: str) -> bool:
    """Проверяет, что строка — только название услуги, без чисел и сумм."""
    return len(line) > 3 and bool(_SERVICE_NAME_ONLY_RE.match(line))


def _collect_name_lines(lines: list[str], start: int) -> tuple[list[str], int]:
    """Собирает подряд идущие строки-названия начиная с индекса start.

    Args:
        lines: Строки текста PDF.
        start: Индекс строки, с которой начинается поиск.

    Returns:
        Собранные названия и индекс следующей значимой строки.
    """
    names: list[str] = []
    i = start
    while i < len(lines):
        candidate = lines[i].strip()
        # Пустая строка разделяет блоки текста: хвост названия так далеко не тянется.
        if not candidate:
            break
        lower = candidate.lower()
        if (
            lower in SECTION_HEADERS
            or lower.startswith("всего")
            or lower.startswith("итого")
            or not _is_service_name_line(candidate)
        ):
            break
        names.append(_clean_service_name(candidate))
        i += 1
    return names, i


def _take_name_tail(
    lines: list[str], start: int, item: dict[str, Any]
) -> tuple[str | None, int]:
    """Забирает строки-продолжения названия после строки с числами.

    Хвост названия (например, «ПУ (Д1)») дописывается к разобранной услуге.
    Если за собранными строками идёт строка с числами, это название
    следующей услуги — оно возвращается как ожидающее разбора.

    Args:
        lines: Строки текста PDF.
        start: Индекс строки сразу после строки с числами.
        item: Только что разобранная строка услуги.

    Returns:
        Название следующей услуги (или None) и индекс следующей
        неразобранной строки.
    """
    names, i = _collect_name_lines(lines, start)
    if not names:
        return None, i
    if i < len(lines) and _CONTINUATION_RE.match(lines[i].strip()):
        return " ".join(names), i
    item["service_name"] = f'{item["service_name"]} {" ".join(names)}'
    return None, i


def _parse_line_items_from_text(text: str) -> list[dict[str, Any]]:
    """
    Парсит строки услуг из текста PDF.

    Обрабатывает два формата:
    1. Однострочный: SERVICE QUANTITY UNIT TARIFF SUMS
    2. Двухстрочный: SERVICE (строка 1) + QUANTITY UNIT TARIFF SUMS (строка 2)
    SUMS — 4 суммы (без перерасчётов) или 5 (с колонкой «Перерасчёты»).
    Хвост названия после строки с числами дописывается к предыдущей услуге,
    если за ним нет строки с числами.
    """
    items: list[dict[str, Any]] = []
    lines = text.split("\n")
    pending_service: str | None = None
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()
        i += 1
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
            service = _clean_service_name(m.group("service"))
            if service.lower() in SECTION_HEADERS:
                pending_service = None
                continue
            items.append(_make_item(service, m.groupdict()))
            pending_service, i = _take_name_tail(lines, i, items[-1])
            continue

        # Пробуем числовую строку-продолжение (данные для предыдущего service name)
        if pending_service:
            m = _CONTINUATION_RE.match(stripped)
            if m:
                items.append(_make_item(pending_service, m.groupdict()))
                pending_service, i = _take_name_tail(lines, i, items[-1])
                continue

        # Строка только с кириллическим текстом — потенциальное название услуги
        # (для двухстрочного формата: ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ / СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ)
        if _is_service_name_line(stripped):
            name = _clean_service_name(stripped)
            pending_service = f"{pending_service} {name}" if pending_service else name
            continue

        pending_service = None

    return items


def _insurance_total_key(label: str) -> str | None:
    """Определяет, к какому итогу относится строка: с учётом или без учёта страхования.

    Args:
        label: Подпись итоговой строки в нижнем регистре.

    Returns:
        Ключ итога (``amount_due_without_insurance`` или ``amount_due_with_insurance``)
        или None, если строка не про страхование.
    """
    if "страхован" not in label:
        return None
    if "без" in label:
        return "amount_due_without_insurance"
    if "с учет" in label:
        return "amount_due_with_insurance"
    return None


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
        amounts = [
            parse_russian_number(n) for n in _FULL_AMOUNT_RE.findall(m.group("amounts"))
        ]
        if len(amounts) == 5:
            charged, recalculation, _debt, paid, total = amounts
        else:
            charged, _debt, paid, total = amounts
            recalculation = None

        key = _insurance_total_key(label)
        if key:
            totals[key] = total
        if key == "amount_due_without_insurance":
            totals["amount_charged"] = charged
            totals["amount_recalculation"] = recalculation
            totals["amount_paid"] = paid

    for m in _ITOGO_RE.finditer(text):
        key = _insurance_total_key(m.group(0).lower())
        if key:
            totals[key] = parse_russian_number(m.group("amount"))

    totals["amount_due"] = _first_not_none(
        totals["amount_due_without_insurance"], totals["amount_due_with_insurance"]
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
    Если в col[6] полная сумма или прочерк либо col[6] пуст, а в col[7] одно
    число, колонки пришли раздельно.
    """
    paid_cell = (col6 or "").strip()
    separate = (
        paid_cell == "-"
        or _FULL_AMOUNT_RE.fullmatch(paid_cell)
        or (not paid_cell and (col7 or "").count(",") < 2)
    )
    if col7 is None or separate:
        return col6, col7
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


def _is_billing_table(table: list[list[str | None]]) -> bool:
    """Проверяет, что таблица pdfplumber — основная таблица начислений.

    Args:
        table: Таблица pdfplumber.

    Returns:
        True, если в таблице не меньше трёх строк, а в заголовке есть «расчет»
        и «услуги» или «жилищно».
    """
    if not table or len(table) < 3:
        return False
    header_text = " ".join((cell or "") for cell in (table[0] or [])).lower()
    return "расчет" in header_text and ("услуги" in header_text or "жилищно" in header_text)


def _parse_line_items_from_tables(tables: list[list[list[str | None]]]) -> list[dict[str, Any]]:
    """
    Находит основную таблицу начислений среди всех таблиц страницы и парсит её.
    Таблица начислений определяется по _is_billing_table.
    """
    for table in tables:
        if _is_billing_table(table):
            items = _billing_table_to_items(table)
            if items:
                return items
    return []


def _ordered_summary_amounts(row: list[str | None]) -> list[Decimal | None]:
    """Собирает суммы строки «Всего …» по порядку следования в ячейках.

    В 7-колоночной таблице границы режут слова и слипаются суммы: «Начислено»
    и «Перерасчёты» оказываются в одной ячейке, остальные колонки съезжают.
    Позиции колонок тогда недостоверны, а порядок сумм сохраняется.

    Первая цифра первой суммы может остаться в ячейке подписи после двоеточия,
    а её остаток — слипнуться с перерасчётом. Такие цифры возвращаем на место.

    Args:
        row: Строка таблицы начислений.

    Returns:
        Суммы в порядке слева направо (без учёта ячейки с подписью).
    """
    label = (row[0] or "").rstrip()
    tail = re.search(r":\s*(?P<digits>\d[\d\s]*)$", label)
    leading = tail.group("digits").strip() if tail else ""
    joined = " ".join(filter(None, [leading, *(cell or "" for cell in row[1:])]))
    return [parse_russian_number(n) for n in _FULL_AMOUNT_RE.findall(joined)]


def _parse_summary_from_table(table: list[list[str | None]], ncols: int) -> dict[str, Any] | None:
    """Извлекает итоговые суммы из строк «Всего за ...» внутри таблицы начислений."""
    totals: dict[str, Any] = {}
    for row in table:
        if not row or not row[0]:
            continue
        label = (row[0] or "").strip().lower()
        if not label.startswith("всего"):
            continue

        key = _insurance_total_key(label)
        ordered = _ordered_summary_amounts(row) if ncols >= 7 else []

        if len(ordered) == 5:
            # Формат с колонкой «Перерасчёты»: порядок сумм надёжнее колонок.
            charged, rekalc, _debt, paid, total = ordered
        elif ncols >= 7:
            charged = parse_russian_number((row[3] or "").strip() if len(row) > 3 else None)
            rekalc = parse_russian_number((row[4] or "").strip() if len(row) > 4 else None)
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
            # В 5-колоночном формате колонки перерасчёта нет: nums[0] — долг, nums[1] — оплачено.
            rekalc = None
            paid = parse_russian_number(nums[1].strip()) if len(nums) > 1 else None

        if key:
            totals[key] = total
        if key == "amount_due_without_insurance":
            totals["amount_charged"] = charged
            totals["amount_recalculation"] = rekalc
            totals["amount_paid"] = paid

    return totals or None


def _parse_merge_totals_from_tables(
    tables: list[list[list[str | None]]],
    result_totals: dict[str, Any],
) -> None:
    """Извлекает итоги из первой таблицы начислений со строками «Всего за …».

    Таблицы начислений без итогов пропускаются: pdfplumber может вернуть
    несколько таблиц начислений, и первая из них бывает пустой.

    Args:
        tables: Таблицы pdfplumber со всех страниц.
        result_totals: Итоги, которые нужно дополнить найденными суммами.
    """
    for table in tables:
        if not _is_billing_table(table):
            continue
        ncols = max(len(row) for row in table)
        summary = _parse_summary_from_table(table, ncols)
        if not summary or all(v is None for v in summary.values()):
            continue
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
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError(f"PDF содержит слишком много страниц (>{MAX_PAGES}).")
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
            result["totals"]["amount_due"] = _first_not_none(
                result["totals"]["amount_due_without_insurance"],
                result["totals"]["amount_due_with_insurance"],
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

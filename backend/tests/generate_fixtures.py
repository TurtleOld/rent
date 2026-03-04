"""
Скрипт генерации синтетических PDF-фикстур для тестов.
Все данные полностью вымышленные — персональных данных нет.

Запуск:
    cd backend
    python tests/generate_fixtures.py
"""
import os
import sys
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError:
    print("ERROR: reportlab не установлен. Выполните: pip install reportlab")
    sys.exit(1)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)
OUTPUT = FIXTURES_DIR / "sample_epd.pdf"

# ─── Шрифты ───

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

_font_path = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)
_bold_path = next((p for p in _BOLD_CANDIDATES if os.path.exists(p)), None)

if not _font_path:
    print("ERROR: не найден шрифт с поддержкой кириллицы")
    sys.exit(1)

pdfmetrics.registerFont(TTFont("CyrFont", _font_path))
pdfmetrics.registerFont(TTFont("CyrFontBold", _bold_path or _font_path))

# ─── Вспомогательные функции ───

_canvas: canvas.Canvas


def text_at(x, y, txt, size=8, bold=False):
    _canvas.setFont("CyrFontBold" if bold else "CyrFont", size)
    _canvas.drawString(x, y, txt)


def hline(y, x1=15 * mm, x2=195 * mm):
    _canvas.setStrokeColor(colors.black)
    _canvas.setLineWidth(0.5)
    _canvas.line(x1, y, x2, y)


def service_row(y, name, qty, unit, tariff, charged, debt, paid, total, sz=7):
    """Рисует строку услуги с фиксированными x-позициями колонок."""
    _canvas.setFont("CyrFont", sz)
    _canvas.drawString(15 * mm, y, name)
    _canvas.drawString(78 * mm, y, qty)
    _canvas.drawString(94 * mm, y, unit)
    _canvas.drawString(109 * mm, y, tariff)
    _canvas.drawString(125 * mm, y, charged)
    _canvas.drawString(145 * mm, y, debt)
    _canvas.drawString(163 * mm, y, paid)
    _canvas.drawString(180 * mm, y, total)


def summary_row(y, label, charged, debt, paid, total):
    _canvas.setFont("CyrFontBold", 7)
    _canvas.drawString(15 * mm, y, label)
    _canvas.setFont("CyrFont", 7)
    _canvas.drawString(125 * mm, y, charged)
    _canvas.drawString(145 * mm, y, debt)
    _canvas.drawString(163 * mm, y, paid)
    _canvas.drawString(180 * mm, y, total)


def meter_row(y, name, ipu, num, date_prev, curr_vol):
    _canvas.setFont("CyrFont", 6.5)
    _canvas.drawString(15 * mm, y, name)
    _canvas.drawString(58 * mm, y, ipu)
    _canvas.drawString(70 * mm, y, num)
    _canvas.drawString(92 * mm, y, date_prev)
    _canvas.drawString(125 * mm, y, curr_vol)


# ─── Генерация ───

def generate():
    global _canvas
    _canvas = canvas.Canvas(str(OUTPUT), pagesize=A4)
    _, h = A4

    y = h - 18 * mm

    # Заголовок
    text_at(40 * mm, y, "ЕДИНЫЙ ПЛАТЕЖНЫЙ ДОКУМЕНТ", 11, bold=True)
    y -= 5 * mm
    text_at(15 * mm, y, "ЖИЛИЩНО-КОММУНАЛЬНЫЕ И ИНЫЕ УСЛУГИ ЗА февраль 2026 г.", 9, bold=True)
    y -= 4.5 * mm
    text_at(15 * mm, y,
            'ВАША УПРАВЛЯЮЩАЯ ОРГАНИЗАЦИЯ: ООО "УК "Солнечный"142700, Московская область, г. Видное,',
            6.5)
    y -= 3 * mm
    text_at(15 * mm, y,
            'ул. Центральная, д. 5, офис 3, +74951234567, ОГРН 1175053099999, ИНН 5001999999, КПП 500101001',
            6.5)
    y -= 3.5 * mm
    text_at(15 * mm, y,
            'ПОЛУЧАТЕЛЬ ПЛАТЕЖА: ООО "РасчётЦентр" ИНН 5037001111 КПП 503701001 р/с 40702810000000001111',
            6.5)
    y -= 3 * mm
    text_at(15 * mm, y,
            'БИК 044525111 к/с 30101810000000000111; 142700, Московская обл., г. Видное, ул. Мира, д. 10, помещ. 100.',
            6.5)

    y -= 5 * mm
    text_at(15 * mm, y, "Лицевой счет: 1 2 3 4 5 - 6 7 8", 9, bold=True)
    text_at(110 * mm, y, "Просим оплатить счет до 10.03.2026", 8)
    y -= 5 * mm
    text_at(15 * mm, y, "ФИО: ИВАНОВ ИВАН ИВАНОВИЧ", 9, bold=True)
    y -= 4.5 * mm
    text_at(15 * mm, y, "Адрес: 142700, МОСКОВСКАЯ ОБЛ., Г. ВИДНОЕ, УЛ СОЛНЕЧНАЯ, д.10, кв.42", 8)

    # Боксы с итогами
    y -= 6 * mm
    _canvas.setLineWidth(1)
    _canvas.rect(15 * mm, y - 13 * mm, 82 * mm, 15 * mm)
    _canvas.rect(102 * mm, y - 13 * mm, 82 * mm, 15 * mm)
    text_at(17 * mm, y - 2.5 * mm, "ИТОГО К ОПЛАТЕ ЗА ВСЕ УСЛУГИ СЧЕТА С", 6.5)
    text_at(17 * mm, y - 5.5 * mm, "УЧЕТОМ ДОБРОВОЛЬНОГО СТРАХОВАНИЯ", 6.5)
    text_at(28 * mm, y - 11 * mm, "5 432 руб. 10 коп.", 10, bold=True)
    text_at(104 * mm, y - 2.5 * mm, "ИТОГО К ОПЛАТЕ ЗА ВСЕ УСЛУГИ СЧЕТА", 6.5)
    text_at(104 * mm, y - 5.5 * mm, "БЕЗ УЧЕТА ДОБРОВОЛЬНОГО СТРАХОВАНИЯ", 6.5)
    text_at(115 * mm, y - 11 * mm, "5 172 руб. 20 коп.", 10, bold=True)
    y -= 20 * mm

    text_at(15 * mm, y, "Информация по Вашему лицевому счету:", 6.5)
    y -= 3 * mm
    text_at(15 * mm, y,
            "Форма собственности: ЧАСТНОЕ, Тип помещения: Квартира, Площадь общая: 48.00 кв.м, "
            "Площадь жилая: 32.50 кв.м, Зарегистрировано: 3 чел.,",
            6)
    y -= 3 * mm
    text_at(15 * mm, y,
            "Проживает: 3 чел. Общ. площадь дома: 5200.000 кв.м, Жилые помещения: 4800.000 кв.м, "
            "Места общего пользования: 400.000 кв.м.",
            6)

    y -= 5 * mm
    text_at(20 * mm, y,
            "РАСЧЕТ РАЗМЕРА ПЛАТЫ ЗА ЖИЛИЩНО-КОММУНАЛЬНЫЕ И ИНЫЕ УСЛУГИ ЗА ФЕВРАЛЬ 2026г.",
            7.5, bold=True)
    y -= 4 * mm

    # Заголовок таблицы
    hline(y + 1.5 * mm)
    _canvas.setFont("CyrFontBold", 6)
    _canvas.drawString(15 * mm, y, "Виды услуг")
    _canvas.drawString(78 * mm, y, "Объем")
    _canvas.drawString(94 * mm, y, "Ед.изм.")
    _canvas.drawString(109 * mm, y, "Тариф,")
    _canvas.drawString(125 * mm, y, "Начислено")
    _canvas.drawString(145 * mm, y, "Задолженность/")
    _canvas.drawString(163 * mm, y, "Оплачено, руб.")
    _canvas.drawString(180 * mm, y, "ИТОГО,")
    y -= 2.5 * mm
    _canvas.drawString(78 * mm, y, "услуг")
    _canvas.drawString(109 * mm, y, "руб.")
    _canvas.drawString(125 * mm, y, "по тарифу,")
    _canvas.drawString(145 * mm, y, "Переплата(-) на")
    _canvas.drawString(180 * mm, y, "руб.")
    y -= 2.5 * mm
    _canvas.drawString(125 * mm, y, "руб.")
    _canvas.drawString(145 * mm, y, "начало периода")
    y -= 1 * mm
    hline(y)
    y -= 3.5 * mm

    # Секция: Жилищные
    text_at(50 * mm, y, "Начисления за жилищные услуги", 6.5)
    y -= 4 * mm

    # ВЗНОС — двухстрочный
    text_at(15 * mm, y, "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ", 7)
    y -= 3.5 * mm
    _canvas.setFont("CyrFont", 7)
    _canvas.drawString(78 * mm, y, "48.00")
    _canvas.drawString(94 * mm, y, "кв.м.")
    _canvas.drawString(109 * mm, y, "24.00")
    _canvas.drawString(125 * mm, y, "1 152,00")
    _canvas.drawString(145 * mm, y, "0,00")
    _canvas.drawString(163 * mm, y, "0,00")
    _canvas.drawString(180 * mm, y, "1 152,00")
    y -= 3.5 * mm

    service_row(y, "ВОДООТВЕДЕНИЕ ОДН", "0.065000", "куб.м.", "58.50", "3,80", "0,00", "0,00", "3,80")
    y -= 3.5 * mm
    service_row(y, "ГОРЯЧАЯ ВОДА (НОСИТЕЛЬ) ОДН", "0.070000", "куб.м.", "65.00", "4,55", "0,00", "0,00", "4,55")
    y -= 3.5 * mm
    service_row(y, "ГОРЯЧЕЕ В/С (ЭНЕРГИЯ) ОДН", "0.004500", "Гкал", "2900.00", "13,05", "-98,30", "0,00", "0,00")
    y -= 3.5 * mm

    # СОДЕРЖАНИЕ — двухстрочный
    text_at(15 * mm, y, "СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ", 7)
    y -= 3.5 * mm
    _canvas.setFont("CyrFont", 7)
    _canvas.drawString(78 * mm, y, "48.00")
    _canvas.drawString(94 * mm, y, "кв.м.")
    _canvas.drawString(109 * mm, y, "42.00")
    _canvas.drawString(125 * mm, y, "2 016,00")
    _canvas.drawString(145 * mm, y, "0,00")
    _canvas.drawString(163 * mm, y, "0,00")
    _canvas.drawString(180 * mm, y, "2 016,00")
    y -= 3.5 * mm

    service_row(y, "ХОЛОДНОЕ В/С ОДН", "0.065000", "куб.м.", "65.00", "4,23", "0,00", "0,00", "4,23")
    y -= 3.5 * mm
    service_row(y, "ЭЛЕКТРОСНАБЖЕНИЕ ОДН", "0.950000", "Квт/ч", "6.50", "6,18", "0,00", "0,00", "6,18")
    y -= 3.5 * mm

    # Секция: Коммунальные
    text_at(50 * mm, y, "Начисления за коммунальные услуги", 6.5)
    y -= 4 * mm

    service_row(y, "ВОДООТВЕДЕНИЕ", "2.50", "куб. м.", "58.50", "146,25", "0,00", "0,00", "146,25")
    y -= 3.5 * mm
    service_row(y, "ГАЗОСНАБЖЕНИЕ", "3", "чел.", "90.00", "270,00", "150,00", "150,00", "270,00")
    y -= 3.5 * mm
    service_row(y, "ГОРЯЧЕЕ В/С (ЭНЕРГИЯ).", "0.0550", "куб.м.", "2900.00", "159,50", "0,00", "0,00", "159,50")
    y -= 3.5 * mm
    service_row(y, "ГОРЯЧЕЕ В/С (НОСИТЕЛЬ)", "0.80", "куб.м.", "65.00", "52,00", "0,00", "0,00", "52,00")
    y -= 3.5 * mm
    service_row(y, "ОБРАЩЕНИЕ С ТКО", "48.00", "кв.м.", "12.000000", "576,00", "0,00", "0,00", "576,00")
    y -= 3.5 * mm
    service_row(y, "ОТОПЛЕНИЕ", "0.7500", "Гкал", "2900.00", "2 175,00", "0,00", "0,00", "2 175,00")
    y -= 3.5 * mm
    service_row(y, "ХОЛОДНОЕ В/С", "1.70", "куб. м.", "65.00", "110,50", "0,00", "0,00", "110,50")
    y -= 3.5 * mm

    # Секция: Иные
    text_at(50 * mm, y, "Начисления за иные услуги", 6.5)
    y -= 4 * mm

    service_row(y, "ЗАПИРАЮЩЕЕ УСТРОЙСТВО", "1.00", "абонент", "60.00", "60,00", "0,00", "0,00", "60,00")
    y -= 3.5 * mm
    service_row(y, "ТО ВКГО", "1.00", "абонент", "125.00", "125,00", "0,00", "0,00", "125,00")
    y -= 3.5 * mm

    hline(y + 1 * mm)
    y -= 1 * mm

    summary_row(y, "Всего за февраль 2026 без учета добровольного страхования:",
                "4 874,06", "51,70", "150,00", "5 172,20")
    y -= 4 * mm

    service_row(y, "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ", "48.00", "кв.м.", "5.41", "259,90", "0,00", "0,00", "259,90")
    y -= 4 * mm

    summary_row(y, "Всего за февраль 2026 с учетом добровольного страхования :",
                "5 133,96", "51,70", "150,00", "5 432,10")
    y -= 4 * mm

    text_at(15 * mm, y,
            "Итого к оплате за февраль 2026 без учета добровольного страхования: 5 172,20",
            7, bold=True)
    y -= 3.5 * mm
    text_at(15 * mm, y,
            "Итого к оплате за февраль 2026 с учетом добровольного страхования: 5 432,10",
            7, bold=True)
    y -= 5 * mm
    text_at(15 * mm, y,
            "Оплата, не учтенная в данном счете, будет включена в следующий платежный документ.",
            6)
    y -= 6 * mm

    # Справочная таблица счётчиков
    text_at(55 * mm, y, "Справочная информация", 7.5, bold=True)
    y -= 4 * mm

    _canvas.setFont("CyrFontBold", 6)
    hline(y + 1.5 * mm)
    _canvas.drawString(15 * mm, y, "Виды услуг")
    _canvas.drawString(58 * mm, y, "ИПУ/")
    _canvas.drawString(70 * mm, y, "Номер")
    _canvas.drawString(92 * mm, y, "Дата")
    _canvas.drawString(115 * mm, y, "Показания приборов учета")
    _canvas.drawString(160 * mm, y, "Объем")
    y -= 2.5 * mm
    _canvas.drawString(58 * mm, y, "ОДПУ")
    _canvas.drawString(70 * mm, y, "прибора")
    _canvas.drawString(92 * mm, y, "поверки")
    _canvas.drawString(115 * mm, y, "коммунальных услуг")
    _canvas.drawString(160 * mm, y, "потребления")
    y -= 2.5 * mm
    _canvas.drawString(70 * mm, y, "учета")
    _canvas.drawString(115 * mm, y, "Предыдущее")
    _canvas.drawString(140 * mm, y, "Текущее")
    y -= 1 * mm
    hline(y)
    y -= 3.5 * mm

    # ИПУ (с реальными показаниями)
    meter_row(y, "ГОРЯЧЕЕ В/С (НОСИТЕЛЬ)", "ИПУ", "100200300",
              "15.06.2030 45.000000", "46.000000 1.000000")
    y -= 3.5 * mm
    meter_row(y, "ХОЛОДНОЕ В/С", "ИПУ", "100200400",
              "15.06.2030 120.000000", "121.700000 1.700000")
    y -= 3.5 * mm

    # ОДПУ (без показаний ИПУ)
    meter_row(y, "ВОДООТВЕДЕНИЕ ОДН", "ОДПУ", "б/н к расчёт", "0.000", "3.500 3.500")
    y -= 3.5 * mm
    meter_row(y, "ГОРЯЧАЯ ВОДА (НОСИТЕЛЬ) ОДН", "ОДПУ", "норматив", "0.000", "0.000 3.600")
    y -= 3.5 * mm
    meter_row(y, "ГОРЯЧЕЕ В/С (ЭНЕРГИЯ) ОДН", "ОДПУ", "норматив", "0.000", "0.000 0.250")
    y -= 3.5 * mm
    meter_row(y, "ХОЛОДНОЕ В/С ОДН", "ОДПУ", "б/н к расчёт", "0.000", "3.500 3.500")
    y -= 3.5 * mm
    meter_row(y, "ЭЛЕКТРОСНАБЖЕНИЕ ОДН", "ОДПУ", "к расчету", "0.000", "48.000 48.000")
    y -= 6 * mm

    text_at(15 * mm, y, "Л/C:  12345678", 9, bold=True)
    y -= 5 * mm
    text_at(15 * mm, y, "Куда: 142700, МОСКОВСКАЯ ОБЛ., Г. ВИДНОЕ, УЛ СОЛНЕЧНАЯ, д.10, кв.42", 8)

    _canvas.save()
    print(f"Сгенерирован: {OUTPUT}")


if __name__ == "__main__":
    generate()

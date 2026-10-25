import unittest
from decimal import Decimal
from pathlib import Path

import pdfplumber

from apps.invoices.pdf_parser import (
    _billing_table_to_items,
    _extract_account_number,
    _extract_address,
    _extract_header_totals,
    _extract_payer_name,
    _extract_period,
    _extract_provider_name,
    _insurance_total_key,
    _is_billing_table,
    _parse_line_items_from_tables,
    _parse_merge_totals_from_tables,
    _parse_meter_readings_from_tables,
    _parse_summary_from_table,
    _parse_summary_totals,
    parse_epd,
    parse_russian_number,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "sample_epd.pdf"
TABLE5_PDF = FIXTURES_DIR / "sample_epd_table5.pdf"
TABLE8_PDF = FIXTURES_DIR / "sample_epd_table8.pdf"


class TestParseRussianNumber(unittest.TestCase):
    def test_simple_integer(self):
        self.assertEqual(parse_russian_number("1243"), Decimal("1243"))

    def test_comma_decimal(self):
        self.assertEqual(parse_russian_number("1 243,00"), Decimal("1243.00"))

    def test_negative(self):
        self.assertEqual(parse_russian_number("-132,45"), Decimal("-132.45"))

    def test_none(self):
        self.assertIsNone(parse_russian_number(None))

    def test_empty(self):
        self.assertIsNone(parse_russian_number(""))

    def test_dash(self):
        self.assertIsNone(parse_russian_number("-"))

    def test_nbsp(self):
        self.assertEqual(parse_russian_number("7\xa0647,29"), Decimal("7647.29"))

    def test_dot_decimal(self):
        self.assertEqual(parse_russian_number("1243.00"), Decimal("1243.00"))

    def test_large_number_with_spaces(self):
        self.assertEqual(parse_russian_number("2 327,03"), Decimal("2327.03"))


class TestExtractPeriod(unittest.TestCase):
    def test_january_2026(self):
        result = _extract_period("УСЛУГИ ЗА январь 2026 г.")
        self.assertEqual(result["month"], 1)
        self.assertEqual(result["year"], 2026)
        self.assertEqual(result["start_date"], "2026-01-01")
        self.assertEqual(result["end_date"], "2026-01-31")

    def test_december(self):
        result = _extract_period("за декабрь 2025 г.")
        self.assertEqual(result["month"], 12)
        self.assertEqual(result["year"], 2025)
        self.assertEqual(result["end_date"], "2025-12-31")

    def test_february_leap_year(self):
        result = _extract_period("за февраль 2028 г.")
        self.assertEqual(result["end_date"], "2028-02-29")

    def test_no_period(self):
        result = _extract_period("some random text")
        self.assertIsNone(result["month"])
        self.assertIsNone(result["year"])


class TestExtractAccountNumber(unittest.TestCase):
    def test_spaced_account(self):
        self.assertEqual(
            _extract_account_number("Лицевой счет: 8 1 9 6 7 - 6 4 2"),
            "81967642",
        )

    def test_no_spaces(self):
        self.assertEqual(
            _extract_account_number("Лицевой счёт: 12345678"),
            "12345678",
        )

    def test_no_account(self):
        self.assertIsNone(_extract_account_number("no account here"))


class TestExtractPayerName(unittest.TestCase):
    def test_payer(self):
        self.assertEqual(
            _extract_payer_name("ФИО: ПАВЛОВ АЛЕКСАНДР ВАЛЕНТИНОВИЧ"),
            "ПАВЛОВ АЛЕКСАНДР ВАЛЕНТИНОВИЧ",
        )

    def test_no_payer(self):
        self.assertIsNone(_extract_payer_name("some text"))


class TestExtractAddress(unittest.TestCase):
    def test_address(self):
        result = _extract_address("Адрес: 143921, МОСКОВСКАЯ ОБЛ., д.30, кв.16")
        self.assertEqual(result, "143921, МОСКОВСКАЯ ОБЛ., д.30, кв.16")

    def test_no_address(self):
        self.assertIsNone(_extract_address("no address"))


class TestExtractProviderName(unittest.TestCase):
    def test_nested_quotes(self):
        text = 'УПРАВЛЯЮЩАЯ ОРГАНИЗАЦИЯ: ООО "УК "Энтузиаст"143912, Московская'
        self.assertEqual(_extract_provider_name(text), 'ООО "УК "Энтузиаст"')

    def test_no_provider(self):
        self.assertIsNone(_extract_provider_name("random text"))


@unittest.skipUnless(SAMPLE_PDF.exists(), "Sample PDF not found in fixtures")
class TestParseEpdIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(SAMPLE_PDF, "rb") as f:
            cls.result = parse_epd(f)

    def test_document_type(self):
        self.assertEqual(self.result["document_type"], "utility_bill")

    def test_provider_name(self):
        self.assertIn("Солнечный", self.result["provider_name"])

    def test_account_number(self):
        self.assertEqual(self.result["account_number"], "12345678")

    def test_payer_name(self):
        self.assertEqual(
            self.result["payer_name"], "ИВАНОВ ИВАН ИВАНОВИЧ"
        )

    def test_address(self):
        self.assertIn("СОЛНЕЧНАЯ", self.result["address"])
        self.assertIn("кв.42", self.result["address"])

    def test_period(self):
        period = self.result["period"]
        self.assertEqual(period["month"], 2)
        self.assertEqual(period["year"], 2026)
        self.assertEqual(period["start_date"], "2026-02-01")
        self.assertEqual(period["end_date"], "2026-02-28")

    def test_line_items_count(self):
        self.assertEqual(len(self.result["line_items"]), 17)

    def test_no_section_headers_in_items(self):
        for item in self.result["line_items"]:
            name_lower = item["service_name"].lower()
            self.assertNotIn("начисления за", name_lower)

    def test_no_summary_rows_in_items(self):
        for item in self.result["line_items"]:
            name_lower = item["service_name"].lower()
            self.assertFalse(name_lower.startswith("всего"))
            self.assertFalse(name_lower.startswith("итого"))

    def test_kapitalny_remont(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ"]
        self.assertEqual(item["quantity"], Decimal("48.00"))
        self.assertEqual(item["unit"], "кв.м.")
        self.assertEqual(item["tariff"], Decimal("24.00"))
        self.assertEqual(item["amount_charged"], Decimal("1152.00"))
        self.assertEqual(item["amount"], Decimal("1152.00"))

    def test_otoplenie(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ОТОПЛЕНИЕ"]
        self.assertEqual(item["amount_charged"], Decimal("2175.00"))
        self.assertEqual(item["tariff"], Decimal("2900.00"))

    def test_negative_debt(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ГОРЯЧЕЕ В/С (ЭНЕРГИЯ) ОДН"]
        self.assertEqual(item["debt"], Decimal("-98.30"))
        self.assertEqual(item["amount"], Decimal("0.00"))

    def test_gazosnabzhenie_debt(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ГАЗОСНАБЖЕНИЕ"]
        self.assertEqual(item["debt"], Decimal("150.00"))
        self.assertEqual(item["amount"], Decimal("270.00"))

    def test_dobrovolnoe_strakhovanie(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ"]
        self.assertEqual(item["amount_charged"], Decimal("259.90"))

    def test_totals_without_insurance(self):
        self.assertEqual(
            self.result["totals"]["amount_due_without_insurance"],
            Decimal("5172.20"),
        )

    def test_totals_with_insurance(self):
        self.assertEqual(
            self.result["totals"]["amount_due_with_insurance"],
            Decimal("5432.10"),
        )

    def test_totals_amount_due(self):
        self.assertEqual(
            self.result["totals"]["amount_due"], Decimal("5172.20")
        )

    def test_totals_amount_charged(self):
        self.assertEqual(
            self.result["totals"]["amount_charged"], Decimal("4874.06")
        )

    def test_totals_amount_paid(self):
        self.assertEqual(
            self.result["totals"]["amount_paid"], Decimal("150.00")
        )

    def test_totals_debt_is_not_recalculation(self):
        # 51,70 в фикстуре — колонка «Задолженность/Переплата», а не перерасчёт.
        self.assertIsNone(self.result["totals"]["amount_recalculation"])

    def test_totals_currency(self):
        self.assertEqual(self.result["totals"]["currency"], "RUB")

    def test_meter_hot_water(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ГОРЯЧЕЕ В/С (НОСИТЕЛЬ)"]
        self.assertEqual(item["meter_id"], "100200300")
        self.assertEqual(item["previous_reading"], Decimal("45.000000"))
        self.assertEqual(item["current_reading"], Decimal("46.000000"))

    def test_meter_cold_water(self):
        items_by_name = {i["service_name"]: i for i in self.result["line_items"]}
        item = items_by_name["ХОЛОДНОЕ В/С"]
        self.assertEqual(item["meter_id"], "100200400")
        self.assertEqual(item["previous_reading"], Decimal("120.000000"))
        self.assertEqual(item["current_reading"], Decimal("121.700000"))

    def test_confidence(self):
        self.assertEqual(self.result["confidence"], 1.0)

    def test_no_warnings(self):
        self.assertEqual(self.result["warnings"], [])


class TestZeroAmountDue(unittest.TestCase):
    def test_zero_without_insurance_is_not_replaced(self):
        text = (
            "Итого к оплате за январь 2026 без учета добровольного страхования: 0,00\n"
            "Итого к оплате за январь 2026 с учетом добровольного страхования: 45,00"
        )
        totals = _parse_summary_totals(text)
        self.assertEqual(totals["amount_due"], Decimal("0.00"))

    def test_negative_without_insurance_is_parsed(self):
        text = (
            "Итого к оплате за январь 2026 без учета добровольного страхования: -1 234,56\n"
            "Итого к оплате за январь 2026 с учетом добровольного страхования: 45,00"
        )
        totals = _parse_summary_totals(text)
        self.assertEqual(totals["amount_due"], Decimal("-1234.56"))


class TestInsuranceTotalKey(unittest.TestCase):
    def test_without_insurance(self):
        self.assertEqual(
            _insurance_total_key("всего за январь 2026 без учета добровольного страхования"),
            "amount_due_without_insurance",
        )

    def test_with_insurance(self):
        self.assertEqual(
            _insurance_total_key("итого к оплате с учетом добровольного страхования"),
            "amount_due_with_insurance",
        )

    def test_unrelated_label(self):
        self.assertIsNone(_insurance_total_key("всего за январь 2026"))


class TestIsBillingTable(unittest.TestCase):
    def test_billing_header(self):
        table = [["Расчет размера платы за жилищно-коммунальные услуги"], ["a"], ["b"]]
        self.assertTrue(_is_billing_table(table))

    def test_other_header(self):
        self.assertFalse(_is_billing_table([["Показания приборов учета"], ["a"], ["b"]]))

    def test_too_short(self):
        self.assertFalse(_is_billing_table([["Расчет платы за услуги"], ["a"]]))


class _TableFixtureMixin:
    """Загружает ЕПД с рамками таблиц: таблицы pdfplumber и результат parse_epd."""

    pdf_path: Path

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with pdfplumber.open(cls.pdf_path) as pdf:
            cls.tables = [t for page in pdf.pages for t in page.extract_tables()]
        with open(cls.pdf_path, "rb") as f:
            cls.result = parse_epd(f)
        cls.items = {i["service_name"]: i for i in cls.result["line_items"]}

    def table_totals(self):
        totals = {}
        _parse_merge_totals_from_tables(self.tables, totals)
        return totals

    def test_billing_table_found(self):
        # Без этой проверки фикстура могла бы незаметно уйти на текстовый разбор.
        self.assertTrue(_parse_line_items_from_tables(self.tables))

    def test_meter_table_found(self):
        self.assertTrue(_parse_meter_readings_from_tables(self.tables))

    def test_meter_readings_from_table(self):
        self.assertEqual(
            _parse_meter_readings_from_tables(self.tables),
            {
                "ГОРЯЧЕЕ В/С (НОСИТЕЛЬ)": {
                    "meter_id": "100200300",
                    "previous_reading": Decimal("45.000000"),
                    "current_reading": Decimal("46.000000"),
                },
                "ХОЛОДНОЕ В/С": {
                    "meter_id": "100200400",
                    "previous_reading": Decimal("120.000000"),
                    "current_reading": Decimal("121.700000"),
                },
            },
        )

    def test_meter_merged_into_item(self):
        item = self.items["ХОЛОДНОЕ В/С"]
        self.assertEqual(item["meter_id"], "100200400")
        self.assertEqual(item["current_reading"], Decimal("121.700000"))

    def test_no_warnings(self):
        self.assertEqual(self.result["warnings"], [])
        self.assertEqual(self.result["confidence"], 1.0)


class TestTable5Format(_TableFixtureMixin, unittest.TestCase):
    """ЕПД без перерасчётов: таблица начислений в 5 колонок."""

    pdf_path = TABLE5_PDF

    def test_five_columns(self):
        billing = next(t for t in self.tables if "РАСЧЕТ" in (t[0][0] or ""))
        self.assertEqual(max(len(row) for row in billing), 5)

    def test_line_items_count(self):
        self.assertEqual(len(self.result["line_items"]), 9)

    def test_quantity_in_service_cell(self):
        # Объём перенесён второй строкой в ячейку названия услуги.
        item = self.items["ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ"]
        self.assertEqual(item["quantity"], Decimal("48.00"))
        self.assertEqual(item["unit"], "кв.м.")
        self.assertEqual(item["tariff"], Decimal("24.00"))
        self.assertEqual(item["amount_charged"], Decimal("1152.00"))
        self.assertEqual(item["debt"], Decimal("0.00"))
        self.assertEqual(item["amount"], Decimal("1152.00"))

    def test_debt_and_paid_in_one_cell(self):
        item = self.items["ГАЗОСНАБЖЕНИЕ"]
        self.assertEqual(item["quantity"], Decimal("3"))
        self.assertEqual(item["unit"], "чел.")
        self.assertEqual(item["tariff"], Decimal("90.00"))
        self.assertEqual(item["amount_charged"], Decimal("270.00"))
        self.assertEqual(item["debt"], Decimal("150.00"))
        self.assertEqual(item["amount"], Decimal("270.00"))

    def test_negative_debt(self):
        item = self.items["ГОРЯЧЕЕ В/С (ЭНЕРГИЯ) ОДН"]
        self.assertEqual(item["quantity"], Decimal("0.004500"))
        self.assertEqual(item["tariff"], Decimal("2900.00"))
        self.assertEqual(item["amount_charged"], Decimal("13.05"))
        self.assertEqual(item["debt"], Decimal("-98.30"))
        self.assertEqual(item["amount"], Decimal("0.00"))

    def test_no_recalculation(self):
        for item in self.result["line_items"]:
            self.assertIsNone(item["recalculation"])
        self.assertIsNone(self.result["totals"]["amount_recalculation"])

    def test_totals_from_table(self):
        self.assertEqual(self.table_totals(), {
            "amount_charged": Decimal("5848.55"),
            "amount_paid": Decimal("150.00"),
            "amount_due_without_insurance": Decimal("5835.50"),
            "amount_due_with_insurance": Decimal("6095.18"),
        })

    def test_amount_due(self):
        self.assertEqual(self.result["totals"]["amount_due"], Decimal("5835.50"))


class TestTable8Format(_TableFixtureMixin, unittest.TestCase):
    """ЕПД с перерасчётами: 8 колонок, «Оплачено» и «ИТОГО» слиплись."""

    pdf_path = TABLE8_PDF

    def test_eight_columns(self):
        billing = next(t for t in self.tables if "РАСЧЕТ" in (t[0][0] or ""))
        self.assertEqual(max(len(row) for row in billing), 8)

    def test_paid_and_total_cells_glued(self):
        # Фикстура должна воспроизводить разрез числа «2,96» границей колонок.
        billing = next(t for t in self.tables if "РАСЧЕТ" in (t[0][0] or ""))
        row = next(r for r in billing if r[0] == "ХОЛОДНОЕ В/С")
        self.assertEqual(row[6:], ["2,9", "6 110,50"])

    def test_line_items_count(self):
        self.assertEqual(len(self.result["line_items"]), 8)

    def test_negative_recalculation(self):
        item = self.items["ГОРЯЧЕЕ В/С (НОСИТЕЛЬ)"]
        self.assertEqual(item["quantity"], Decimal("0.80"))
        self.assertEqual(item["unit"], "куб.м.")
        self.assertEqual(item["tariff"], Decimal("65.00"))
        self.assertEqual(item["amount_charged"], Decimal("52.00"))
        self.assertEqual(item["recalculation"], Decimal("-12.30"))
        self.assertEqual(item["debt"], Decimal("0.00"))
        self.assertEqual(item["amount"], Decimal("39.70"))

    def test_positive_recalculation(self):
        item = self.items["ОТОПЛЕНИЕ"]
        self.assertEqual(item["quantity"], Decimal("0.7500"))
        self.assertEqual(item["unit"], "Гкал")
        self.assertEqual(item["tariff"], Decimal("2900.00"))
        self.assertEqual(item["amount_charged"], Decimal("2175.00"))
        self.assertEqual(item["recalculation"], Decimal("145.00"))
        self.assertEqual(item["amount"], Decimal("2320.00"))

    def test_glued_paid_and_total(self):
        item = self.items["ХОЛОДНОЕ В/С"]
        self.assertEqual(item["debt"], Decimal("2.96"))
        self.assertEqual(item["amount"], Decimal("110.50"))

    def test_totals_from_table(self):
        self.assertEqual(self.table_totals(), {
            "amount_charged": Decimal("5835.50"),
            "amount_recalculation": Decimal("132.70"),
            "amount_paid": Decimal("152.96"),
            "amount_due_without_insurance": Decimal("5968.20"),
            "amount_due_with_insurance": Decimal("6227.88"),
        })

    def test_amount_due(self):
        self.assertEqual(self.result["totals"]["amount_due"], Decimal("5968.20"))


class TestPaidAndTotalColumns(unittest.TestCase):
    """«Оплачено» и «ИТОГО» в 8-колоночной таблице: слипшиеся и раздельные ячейки."""

    def table(self, paid_cell, total_cell):
        return [
            ["РАСЧЕТ РАЗМЕРА ПЛАТЫ ЗА ЖИЛИЩНО-КОММУНАЛЬНЫЕ УСЛУГИ"] + [None] * 7,
            ["ХОЛОДНОЕ В/С", "2.0", "куб.м. 40.73", "81,46", "0,00", "2,96", paid_cell, total_cell],
            ["Всего за январь 2026 без учета добровольного страхования",
             None, None, "81,46", "0,00", "2,96", paid_cell, total_cell],
        ]

    def test_separate_service_row(self):
        items = _billing_table_to_items(self.table("2,96", "81,59"))
        self.assertEqual(items[0]["amount"], Decimal("81.59"))

    def test_glued_service_row(self):
        items = _billing_table_to_items(self.table("2,9", "6 81,59"))
        self.assertEqual(items[0]["amount"], Decimal("81.59"))

    def test_separate_summary_row(self):
        totals = _parse_summary_from_table(self.table("2,96", "81,59"), 8)
        self.assertEqual(totals["amount_paid"], Decimal("2.96"))
        self.assertEqual(totals["amount_due_without_insurance"], Decimal("81.59"))

    def test_glued_summary_row(self):
        totals = _parse_summary_from_table(self.table("2,9", "6 81,59"), 8)
        self.assertEqual(totals["amount_paid"], Decimal("2.96"))
        self.assertEqual(totals["amount_due_without_insurance"], Decimal("81.59"))


class TestExtractHeaderTotals(unittest.TestCase):
    def amounts(self, rub_kop):
        # Одна и та же сумма в обоих полях шапки: правило должно быть общим.
        totals = _extract_header_totals(f"К оплате {rub_kop} Без страхования {rub_kop}")
        return totals["amount_due_with_insurance"], totals["amount_due_without_insurance"]

    def test_single_digit_kopecks(self):
        self.assertEqual(self.amounts("1234 руб. 5 коп."), (Decimal("1234.05"),) * 2)

    def test_two_digit_kopecks(self):
        self.assertEqual(self.amounts("1234 руб. 05 коп."), (Decimal("1234.05"),) * 2)

    def test_rubles_with_spaces(self):
        self.assertEqual(self.amounts("5 432 руб. 10 коп."), (Decimal("5432.10"),) * 2)

    def test_negative_overpayment(self):
        self.assertEqual(self.amounts("-5 172 руб. 20 коп."), (Decimal("-5172.20"),) * 2)

    def test_single_amount_is_without_insurance(self):
        totals = _extract_header_totals("К оплате 1234 руб. 5 коп.")
        self.assertEqual(totals["amount_due_without_insurance"], Decimal("1234.05"))

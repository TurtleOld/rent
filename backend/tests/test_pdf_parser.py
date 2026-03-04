import unittest
from decimal import Decimal
from pathlib import Path

from apps.invoices.pdf_parser import (
    _extract_account_number,
    _extract_address,
    _extract_payer_name,
    _extract_period,
    _extract_provider_name,
    parse_epd,
    parse_russian_number,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "sample_epd.pdf"


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

    def test_totals_recalculation(self):
        self.assertEqual(
            self.result["totals"]["amount_recalculation"], Decimal("51.70")
        )

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

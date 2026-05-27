from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.invoices.models import Invoice, LineItem
from apps.invoices.validators import (
    check_invoice_totals,
    check_line_item,
    run_all_checks,
)

User = get_user_model()


def _make_invoice(**kwargs) -> Invoice:
    defaults = {
        "status": Invoice.Status.PROCESSED,
        "warnings": [],
    }
    defaults.update(kwargs)
    invoice = Invoice.__new__(Invoice)
    for k, v in defaults.items():
        setattr(invoice, k, v)
    invoice.pk = None
    return invoice


def _make_line_item(**kwargs) -> LineItem:
    defaults = {
        "service_name": "Тест",
        "quantity": None,
        "tariff": None,
        "amount_charged": None,
        "recalculation": None,
        "debt": None,
        "amount": None,
    }
    defaults.update(kwargs)
    li = LineItem.__new__(LineItem)
    for k, v in defaults.items():
        setattr(li, k, v)
    li.pk = None
    return li


class CheckLineItemTest(TestCase):
    def test_quantity_times_tariff_ok_no_warning(self):
        li = _make_line_item(
            quantity=Decimal("10.0"),
            tariff=Decimal("5.00"),
            amount_charged=Decimal("50.00"),
        )
        self.assertEqual(check_line_item(li), [])

    def test_quantity_times_tariff_off_emits_warning(self):
        li = _make_line_item(
            service_name="Вода",
            quantity=Decimal("10.0"),
            tariff=Decimal("5.00"),
            amount_charged=Decimal("60.00"),
        )
        warnings = check_line_item(li)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Вода", warnings[0])
        self.assertIn("начислено", warnings[0])

    def test_amount_charged_plus_recalc_plus_debt_equals_amount(self):
        li = _make_line_item(
            amount_charged=Decimal("50.00"),
            recalculation=Decimal("5.00"),
            debt=Decimal("2.00"),
            amount=Decimal("57.00"),
        )
        self.assertEqual(check_line_item(li), [])

    def test_totals_mismatch_emits_warning(self):
        li = _make_line_item(
            service_name="Газ",
            amount_charged=Decimal("50.00"),
            recalculation=Decimal("0.00"),
            debt=Decimal("0.00"),
            amount=Decimal("99.00"),
        )
        warnings = check_line_item(li)
        self.assertEqual(len(warnings), 1)
        self.assertIn("итого", warnings[0])

    def test_none_values_dont_explode(self):
        li = _make_line_item()
        self.assertEqual(check_line_item(li), [])

    def test_tolerance_002_passes(self):
        li = _make_line_item(
            quantity=Decimal("3.0"),
            tariff=Decimal("10.00"),
            amount_charged=Decimal("30.02"),
        )
        self.assertEqual(check_line_item(li), [])

    def test_tolerance_exceeds_002_emits_warning(self):
        li = _make_line_item(
            service_name="Свет",
            quantity=Decimal("3.0"),
            tariff=Decimal("10.00"),
            amount_charged=Decimal("30.03"),
        )
        warnings = check_line_item(li)
        self.assertEqual(len(warnings), 1)


class CheckInvoiceTotalsTest(TestCase):
    def _line_items(self, amounts: list[str]) -> list[LineItem]:
        return [_make_line_item(amount=Decimal(a)) for a in amounts]

    def test_totals_match_no_warning(self):
        invoice = _make_invoice(
            amount_due=Decimal("150.00"),
            amount_due_without_insurance=None,
        )
        items = self._line_items(["50.00", "100.00"])
        self.assertEqual(check_invoice_totals(invoice, items), [])

    def test_totals_mismatch_emits_warning(self):
        invoice = _make_invoice(
            amount_due=Decimal("200.00"),
            amount_due_without_insurance=None,
        )
        items = self._line_items(["50.00", "100.00"])
        warnings = check_invoice_totals(invoice, items)
        self.assertEqual(len(warnings), 1)
        self.assertIn("итог квитанции", warnings[0])

    def test_prefers_amount_due_without_insurance(self):
        invoice = _make_invoice(
            amount_due=Decimal("999.00"),
            amount_due_without_insurance=Decimal("150.00"),
        )
        items = self._line_items(["50.00", "100.00"])
        self.assertEqual(check_invoice_totals(invoice, items), [])

    def test_none_amount_due_no_warning(self):
        invoice = _make_invoice(
            amount_due=None,
            amount_due_without_insurance=None,
        )
        items = self._line_items(["50.00"])
        self.assertEqual(check_invoice_totals(invoice, items), [])


class RunAllChecksTest(TestCase):
    def test_run_all_checks_aggregates_warnings(self):
        invoice = _make_invoice(
            amount_due=Decimal("999.00"),
            amount_due_without_insurance=None,
        )
        li = _make_line_item(
            service_name="Свет",
            quantity=Decimal("10.0"),
            tariff=Decimal("5.00"),
            amount_charged=Decimal("99.00"),
            amount=Decimal("99.00"),
        )
        warnings = run_all_checks(invoice, [li])
        self.assertGreaterEqual(len(warnings), 2)

    def test_run_all_checks_clean_invoice(self):
        invoice = _make_invoice(
            amount_due=Decimal("50.00"),
            amount_due_without_insurance=None,
        )
        li = _make_line_item(
            quantity=Decimal("10.0"),
            tariff=Decimal("5.00"),
            amount_charged=Decimal("50.00"),
            amount=Decimal("50.00"),
        )
        self.assertEqual(run_all_checks(invoice, [li]), [])

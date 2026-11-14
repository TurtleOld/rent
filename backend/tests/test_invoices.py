import hashlib
import os
import shutil
import tempfile
import threading
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import (
    NO_SERVICES_WARNING,
    Invoice,
    LineItem,
    Service,
    ServiceAlias,
)
from apps.invoices.validators import check_line_item
from apps.invoices.views import QUEUE_UNAVAILABLE_MESSAGE
from kombu.exceptions import OperationalError

User = get_user_model()

FAKE_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
FAKE_PDF_HASH = hashlib.sha256(FAKE_PDF).hexdigest()

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MULTIPAGE_PDF = FIXTURES_DIR / "sample_epd_multipage.pdf"
TWO_DOCUMENTS_PDF = FIXTURES_DIR / "sample_epd_two_documents.pdf"


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceUploadTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="uploader@example.com",
            email="uploader@example.com",
            password="testpassword",
        )

    def _pdf_file(self):
        return SimpleUploadedFile(
            "test_invoice.pdf", FAKE_PDF, content_type="application/pdf"
        )

    def test_invoice_upload_unauthenticated(self):
        response = self.client.post(
            "/api/invoices/upload/",
            {"pdf_file": self._pdf_file()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_rejects_non_pdf_by_magic_bytes(self):
        self.client.force_authenticate(user=self.user)
        fake_file = SimpleUploadedFile(
            "evil.pdf", b"This is not a PDF file at all", content_type="application/pdf"
        )
        response = self.client.post(
            "/api/invoices/upload/",
            {"pdf_file": fake_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.invoices.views.process_invoice.delay")
    def test_invoice_upload_authenticated(self, mock_delay):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/invoices/upload/",
            {"pdf_file": self._pdf_file()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "processing")
        mock_delay.assert_called_once()

    @patch("apps.invoices.views.process_invoice.delay")
    def test_invoice_belongs_to_user(self, mock_delay):
        self.client.force_authenticate(user=self.user)
        self.client.post(
            "/api/invoices/upload/",
            {"pdf_file": self._pdf_file()},
            format="multipart",
        )
        self.assertEqual(Invoice.objects.filter(user=self.user).count(), 1)

    def test_invoice_list_unauthenticated(self):
        response = self.client.get("/api/invoices/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invoice_model_str(self):
        invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            provider_name="ТСЖ Тест",
        )
        self.assertIn("ТСЖ Тест", str(invoice))

    def test_invoice_model_str_unknown(self):
        invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
        )
        self.assertIn("unknown", str(invoice))


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceDetailTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="viewer@example.com",
            email="viewer@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/fake.pdf",
            status=Invoice.Status.PROCESSED,
            amount_due=Decimal("1500.00"),
        )

    def test_cannot_see_other_users_invoice(self):
        other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="otherpass",
        )
        self.client.force_authenticate(user=other)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_line_item_fields(self):
        item = LineItem.objects.create(
            invoice=self.invoice,
            service_name="ОТОПЛЕНИЕ",
            amount_charged=Decimal("4244.87"),
            recalculation=Decimal("52.03"),
            amount=Decimal("4296.90"),
        )
        self.assertEqual(item.amount_charged + item.recalculation, item.amount)


@override_settings(SECURE_SSL_REDIRECT=False)
class PaymentRemovalTest(TestCase):
    """Ручные платежи и статус оплаты удалены из проекта."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="nopayments@example.com",
            email="nopayments@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/fake.pdf",
            status=Invoice.Status.PROCESSED,
            amount_due=Decimal("1500.00"),
        )
        self.client.force_authenticate(user=self.user)

    def test_payments_app_is_not_installed(self):
        self.assertNotIn("apps.payments", settings.INSTALLED_APPS)

    def test_payments_table_is_dropped(self):
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        self.assertNotIn("payments_payment", tables)

    def test_payments_endpoint_is_gone(self):
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/payments/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invoice_api_has_no_payment_fields(self):
        data = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertNotIn("payment_status", data)
        self.assertNotIn("total_paid", data)


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceAtomicProcessingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="atomic@example.com",
            email="atomic@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
        )
        LineItem.objects.create(
            invoice=self.invoice,
            service_name="СТАРАЯ УСЛУГА",
            amount=Decimal("100.00"),
        )

    def test_reparse_does_not_leave_partial_state(self):
        """Если bulk_create падает, старые LineItem должны остаться."""
        from io import BytesIO

        from django.core.files.base import ContentFile

        from apps.invoices.tasks import _do_process

        self.invoice.pdf_file.save(
            "test.pdf",
            ContentFile(FAKE_PDF),
            save=True,
        )

        original_count = LineItem.objects.filter(invoice=self.invoice).count()
        self.assertEqual(original_count, 1)

        mock_parsed = {
            "document_type": "utility_bill",
            "provider_name": "Тест",
            "account_number": "123",
            "payer_name": None,
            "address": None,
            "period": {"month": 1, "year": 2026, "start_date": None, "end_date": None},
            "totals": {},
            "line_items": [{"service_name": "НОВАЯ УСЛУГА", "amount": "200.00"}],
            "confidence": 0.9,
            "warnings": [],
        }

        with patch("apps.invoices.tasks.parse_epd", return_value=mock_parsed), \
             patch("pdfplumber.open") as mock_open, \
             patch(
                 "apps.invoices.tasks.LineItem.objects.bulk_create",
                 side_effect=DatabaseError("simulated failure"),
             ):
            mock_open.return_value.__enter__.return_value.pages = [None]
            try:
                _do_process(self.invoice)
            except DatabaseError:
                pass

        count_after = LineItem.objects.filter(invoice=self.invoice).count()
        self.assertEqual(count_after, original_count)


@override_settings(SECURE_SSL_REDIRECT=False)
class LineItemQuantityPrecisionTest(TestCase):
    """Количество из ЕПД сохраняется с точностью до 6 знаков."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="precision@example.com",
            email="precision@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _process(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import _do_process

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        mock_parsed = {
            "document_type": "utility_bill",
            "provider_name": "Тест",
            "account_number": "123",
            "payer_name": None,
            "address": None,
            "period": {"month": 1, "year": 2026, "start_date": None, "end_date": None},
            "totals": {},
            "line_items": [
                {
                    "service_name": "ОТОПЛЕНИЕ",
                    "unit": "Гкал",
                    "quantity": "0.954318",
                    "tariff": "2850.12",
                    "amount_charged": "2719.92",
                    "amount": "2719.92",
                }
            ],
            "confidence": 0.9,
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=mock_parsed), \
             patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [None]
            _do_process(self.invoice)

    def test_quantity_saved_with_six_decimals(self):
        self._process()
        li = LineItem.objects.get(invoice=self.invoice)
        self.assertEqual(li.quantity, Decimal("0.954318"))

    def test_exact_quantity_gives_no_product_warning(self):
        self._process()
        self.invoice.refresh_from_db()
        li = LineItem.objects.get(invoice=self.invoice)
        self.assertEqual(check_line_item(li), [])
        self.assertFalse(
            any("количество × тариф" in w for w in self.invoice.warnings)
        )

    def test_api_returns_full_quantity(self):
        self._process()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Хранилище хранит 7 знаков, поэтому сериализатор дополняет нулём.
        self.assertEqual(response.data["line_items"][0]["quantity"], "0.9543180")


@override_settings(SECURE_SSL_REDIRECT=False)
class LineItemSourcePrecisionTest(TestCase):
    """Объём и тариф сохраняются так, как напечатаны в ЕПД."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="source-precision@example.com",
            email="source-precision@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )
        from pathlib import Path

        from django.core.files.base import ContentFile

        with open(Path(__file__).parent / "fixtures" / "sample_epd_precision.pdf", "rb") as f:
            self.invoice.pdf_file.save("precision.pdf", ContentFile(f.read()), save=True)

    def _process(self):
        from apps.invoices.tasks import _do_process

        _do_process(self.invoice)

    def _line_item(self):
        self.invoice.refresh_from_db()
        return LineItem.objects.get(invoice=self.invoice)

    def test_source_values_saved_exactly(self):
        self._process()
        li = self._line_item()
        self.assertEqual(li.quantity, Decimal("0.2468137"))
        self.assertEqual(li.tariff, Decimal("76543.654321"))

    def test_api_returns_source_precision(self):
        self._process()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data["line_items"][0]
        self.assertEqual(item["quantity"], "0.2468137")
        self.assertEqual(item["tariff"], "76543.654321")

    def test_charge_uses_source_precision_without_warning(self):
        self._process()
        li = self._line_item()
        self.assertEqual(li.amount_charged, Decimal("18892.02"))
        self.assertEqual(check_line_item(li), [])
        self.assertFalse(
            any("количество × тариф" in w for w in self.invoice.warnings)
        )

    def test_reparse_keeps_source_precision(self):
        self._process()
        self._process()
        li = self._line_item()
        self.assertEqual(li.quantity, Decimal("0.2468137"))
        self.assertEqual(li.tariff, Decimal("76543.654321"))


@override_settings(SECURE_SSL_REDIRECT=False)
class LineItemPaidTest(TestCase):
    """«Оплачено по ЕПД» сохраняется из парсера и отдаётся в API строк услуг."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="paid@example.com",
            email="paid@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _process(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import _do_process

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        mock_parsed = {
            "document_type": "utility_bill",
            "provider_name": "Тест",
            "account_number": "123",
            "payer_name": None,
            "address": None,
            "period": {"month": 1, "year": 2026, "start_date": None, "end_date": None},
            "totals": {},
            "line_items": [
                {
                    "service_name": "ВОДООТВЕДЕНИЕ ОДН",
                    "unit": "куб.м",
                    "quantity": "0.00",
                    "tariff": "40.00",
                    "amount_charged": "0.00",
                    "recalculation": "70.00",
                    "debt": "40.00",
                    "paid": "40.00",
                    "amount": "70.00",
                }
            ],
            "confidence": 0.9,
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=mock_parsed), \
             patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [None]
            _do_process(self.invoice)

    def test_paid_saved_from_parser(self):
        self._process()
        li = LineItem.objects.get(invoice=self.invoice)
        self.assertEqual(li.paid, Decimal("40.00"))

    def test_no_arithmetic_warning_when_paid_subtracted(self):
        self._process()
        self.invoice.refresh_from_db()
        self.assertFalse(
            any("итого" in w for w in self.invoice.warnings)
        )

    def test_api_returns_paid(self):
        self._process()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["line_items"][0]["paid"], "40.00")


@override_settings(SECURE_SSL_REDIRECT=False)
class MultipageInvoiceTest(TestCase):
    """Многостраничная квитанция обрабатывается целиком, без обрезанных услуг."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="multipage@example.com",
            email="multipage@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _process(self, fixture: Path) -> None:
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self.invoice.pdf_file.save(
            "multipage.pdf", ContentFile(fixture.read_bytes()), save=True
        )
        process_invoice(self.invoice.pk)
        self.invoice.refresh_from_db()

    def test_all_services_saved_with_exact_amounts(self):
        self._process(MULTIPAGE_PDF)

        self.assertEqual(self.invoice.status, Invoice.Status.PROCESSED)
        items = {li.service_name: li for li in self.invoice.line_items.all()}
        self.assertEqual(set(items), {
            "СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ",
            "ТЕКУЩИЙ РЕМОНТ",
            "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ",
        })
        self.assertEqual(items["СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ"].amount, Decimal("1200.00"))
        self.assertEqual(items["СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ"].paid, Decimal("100.00"))
        self.assertEqual(items["ТЕКУЩИЙ РЕМОНТ"].amount, Decimal("800.00"))
        self.assertEqual(items["ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ"].amount, Decimal("96.00"))
        self.assertEqual(self.invoice.amount_due, Decimal("2000.00"))
        self.assertEqual(self.invoice.amount_paid_ai, Decimal("100.00"))
        self.assertEqual(self.invoice.amount_due_without_insurance, Decimal("2000.00"))
        self.assertEqual(self.invoice.amount_due_with_insurance, Decimal("2096.00"))

    def test_no_false_line_total_warning(self):
        self._process(MULTIPAGE_PDF)

        self.assertFalse(any("Сумма по строкам" in w for w in self.invoice.warnings))
        self.assertEqual(self.invoice.warnings, [])

    def test_api_returns_every_service(self):
        self._process(MULTIPAGE_PDF)

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        amounts = {i["service_name"]: i["amount"] for i in response.data["line_items"]}
        self.assertEqual(amounts, {
            "СОДЕРЖАНИЕ ЖИЛОГО ПОМЕЩЕНИЯ": "1200.00",
            "ТЕКУЩИЙ РЕМОНТ": "800.00",
            "ДОБРОВОЛЬНОЕ СТРАХОВАНИЕ": "96.00",
        })

    def test_two_documents_fail_with_clear_error(self):
        self._process(TWO_DOCUMENTS_PDF)

        self.assertEqual(self.invoice.status, Invoice.Status.FAILED)
        self.assertIn("несколько квитанций", self.invoice.error_message)
        self.assertEqual(LineItem.objects.filter(invoice=self.invoice).count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceFileDownloadTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="testpassword",
        )
        self.other_user = User.objects.create_user(
            username="stranger@example.com",
            email="stranger@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
        )

    def test_file_download_requires_auth(self):
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/file/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_file_download_forbidden_for_other_user(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/file/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_file_download_returns_x_accel_redirect_header(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/file/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("X-Accel-Redirect", response)
        self.assertIn("invoices/test.pdf", response["X-Accel-Redirect"])


@override_settings(SECURE_SSL_REDIRECT=False)
class ServiceResolutionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="svc@example.com",
            email="svc@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _run_do_process(self, line_items_data: list[dict]) -> None:
        from django.core.files.base import ContentFile
        from apps.invoices.tasks import _do_process

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        self.invoice.status = Invoice.Status.PROCESSING
        self.invoice.save()

        mock_parsed = {
            "document_type": "utility_bill",
            "provider_name": "Тест",
            "account_number": "123",
            "payer_name": None,
            "address": None,
            "period": {"month": 1, "year": 2026, "start_date": None, "end_date": None},
            "totals": {},
            "line_items": line_items_data,
            "confidence": 0.9,
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=mock_parsed), \
             patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [None]
            _do_process(self.invoice)

    def test_parsing_creates_service_for_new_name(self):
        self._run_do_process([{"service_name": "НОВАЯ УСЛУГА", "unit": "кВт·ч", "amount": "100.00"}])
        self.assertTrue(Service.objects.filter(user=self.user, canonical_name="НОВАЯ УСЛУГА").exists())
        self.assertTrue(ServiceAlias.objects.filter(raw_name="НОВАЯ УСЛУГА").exists())
        li = LineItem.objects.get(invoice=self.invoice, service_name="НОВАЯ УСЛУГА")
        self.assertIsNotNone(li.service)

    def test_parsing_reuses_existing_service_via_alias(self):
        existing = Service.objects.create(user=self.user, canonical_name="ХВС")
        ServiceAlias.objects.create(service=existing, raw_name="ХОЛОДНОЕ ВОДОСНАБЖЕНИЕ")

        self._run_do_process([{"service_name": "ХОЛОДНОЕ ВОДОСНАБЖЕНИЕ", "unit": "куб.м", "amount": "50.00"}])

        li = LineItem.objects.get(invoice=self.invoice, service_name="ХОЛОДНОЕ ВОДОСНАБЖЕНИЕ")
        self.assertEqual(li.service, existing)
        self.assertEqual(Service.objects.filter(user=self.user).count(), 1)

    def test_parsing_normalizes_units(self):
        self._run_do_process([{"service_name": "ТЕСТ", "unit": "куб.м.", "amount": "10.00"}])
        li = LineItem.objects.get(invoice=self.invoice, service_name="ТЕСТ")
        self.assertEqual(li.unit, "куб.м")


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceReadOnlyTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="readonly@example.com",
            email="readonly@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
            provider_name="ТСЖ Тест",
        )

    def test_patch_invoice_returns_405(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f"/api/invoices/{self.invoice.pk}/",
            {"provider_name": "Изменённый поставщик"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceReparseTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="reparse@example.com",
            email="reparse@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
            warnings=["старое предупреждение"],
            error_message="старая ошибка",
        )

    @patch("apps.invoices.views.process_invoice.delay")
    def test_reparse_resets_status_and_dispatches_task(self, mock_delay):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], "processing")
        self.assertEqual(response.data["warnings"], [])
        self.assertIsNone(response.data["error_message"])
        mock_delay.assert_called_once_with(self.invoice.pk)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PROCESSING)

    def test_reparse_returns_409_if_already_processing(self):
        self.invoice.status = Invoice.Status.PROCESSING
        self.invoice.save()
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch("apps.invoices.views.process_invoice.delay")
    def test_reparse_allowed_if_processing_is_stuck(self, mock_delay):
        from datetime import timedelta

        from django.utils import timezone

        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(minutes=10),
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once_with(self.invoice.pk)

    def test_reparse_requires_auth(self):
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reparse_forbidden_for_other_user(self):
        other = User.objects.create_user(
            username="other2@example.com",
            email="other2@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=other)
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProcessInvoiceFailureTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fail@example.com",
            email="fail@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _run(self, **patch_kwargs):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        with patch("apps.invoices.tasks.parse_epd", **patch_kwargs):
            process_invoice(self.invoice.pk)
        self.invoice.refresh_from_db()

    def test_parse_error_marks_failed(self):
        self._run(side_effect=ValueError("broken"))
        self.assertEqual(self.invoice.status, Invoice.Status.FAILED)
        self.assertIn("broken", self.invoice.error_message)

    def test_db_error_marks_failed_instead_of_staying_processing(self):
        parsed = {"period": {}, "totals": {}, "line_items": [], "warnings": []}
        with patch("apps.invoices.tasks.transaction.atomic", side_effect=DatabaseError("db down")):
            self._run(return_value=parsed)
        self.assertEqual(self.invoice.status, Invoice.Status.FAILED)


class DeletedDuringProcessingTest(TestCase):
    """Удалённая во время разбора квитанция не должна воскресать."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="deleted@example.com",
            email="deleted@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _delete_invoice(self) -> None:
        Invoice.objects.filter(pk=self.invoice.pk).delete()

    def test_invoice_deleted_during_parse_is_not_resurrected(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        parsed = {
            "period": {},
            "totals": {"amount_due": "100.00"},
            "line_items": [{"service_name": "ТЕСТ", "amount": "10.00"}],
            "warnings": [],
        }

        def delete_then_parse(_pdf_file):
            self._delete_invoice()
            return parsed

        with patch("apps.invoices.tasks.parse_epd", side_effect=delete_then_parse):
            with self.assertLogs("apps.invoices.tasks", level="WARNING") as logs:
                process_invoice(self.invoice.pk)

        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertFalse(LineItem.objects.filter(invoice_id=self.invoice.pk).exists())
        self.assertTrue(any("удалена" in line for line in logs.output))

    def test_deleted_invoice_parse_error_does_not_raise(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)

        def delete_then_fail(_pdf_file):
            self._delete_invoice()
            raise ValueError("broken")

        with patch("apps.invoices.tasks.parse_epd", side_effect=delete_then_fail):
            with self.assertLogs("apps.invoices.tasks", level="WARNING") as logs:
                process_invoice(self.invoice.pk)

        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertTrue(any("удалена" in line for line in logs.output))


class AmountDueWarningTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            username="nosum@example.com",
            email="nosum@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _process(self, totals: dict) -> None:
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        parsed = {
            "period": {},
            "totals": totals,
            "line_items": [{"service_name": "ОТОПЛЕНИЕ", "amount": "10.00"}],
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=parsed):
            process_invoice(self.invoice.pk)
        self.invoice.refresh_from_db()

    def test_missing_amount_due_adds_warning(self):
        self._process({"amount_due": None})
        self.assertEqual(self.invoice.status, Invoice.Status.PROCESSED)
        self.assertIn("Сумма к оплате не распознана", self.invoice.warnings)

    def test_known_amount_due_adds_no_warning(self):
        self._process({"amount_due": "1500.00"})
        self.assertNotIn("Сумма к оплате не распознана", self.invoice.warnings)


@override_settings(SECURE_SSL_REDIRECT=False)
class ManualAmountDueTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="manual@example.com",
            email="manual@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
            warnings=["Сумма к оплате не распознана"],
        )
        self.client.force_authenticate(user=self.user)

    def _set(self, value, invoice=None):
        invoice = invoice or self.invoice
        return self.client.put(
            f"/api/invoices/{invoice.pk}/manual-amount-due/",
            {"manual_amount_due": value},
            format="json",
        )

    def test_manual_amount_overrides_unknown_amount(self):
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertIsNone(detail["amount_due"])

        response = self._set("1000.00")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount_due"], "1000.00")
        self.assertEqual(response.data["manual_amount_due"], "1000.00")

    def test_reparse_keeps_manual_amount(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        self._set("700.00")
        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=False)
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.PROCESSING, pdf_file=self.invoice.pdf_file.name
        )
        parsed = {
            "period": {},
            "totals": {"amount_due": "1500.00"},
            "line_items": [],
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=parsed):
            process_invoice(self.invoice.pk)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_due, Decimal("1500.00"))
        self.assertEqual(self.invoice.manual_amount_due, Decimal("700.00"))
        data = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertEqual(data["amount_due"], "700.00")

    def test_clearing_returns_recognized_amount(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(amount_due=Decimal("1500.00"))
        for empty in ("", None):
            self._set("700.00")
            response = self._set(empty)
            self.assertEqual(response.status_code, status.HTTP_200_OK, empty)
            self.assertIsNone(response.data["manual_amount_due"])
            self.assertEqual(response.data["amount_due"], "1500.00")

    def test_zero_and_negative_are_accepted(self):
        for value in ("0.00", "-1234.56"):
            response = self._set(value)
            self.assertEqual(response.status_code, status.HTTP_200_OK, value)
            self.assertEqual(response.data["amount_due"], value)

    def test_more_than_two_decimals_rejected(self):
        response = self._set("10.005")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.manual_amount_due)

    def test_rejected_unless_processed(self):
        for state in (Invoice.Status.FAILED, Invoice.Status.PROCESSING, Invoice.Status.INCOMPLETE):
            Invoice.objects.filter(pk=self.invoice.pk).update(status=state)
            response = self._set("700.00")
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, state)
            self.assertEqual(
                response.data["detail"],
                "Сумму к оплате можно ввести только для обработанной квитанции.",
            )
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.manual_amount_due)

    def test_other_users_invoice_cannot_be_changed(self):
        other = User.objects.create_user(
            username="intruder@example.com",
            email="intruder@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=other)
        response = self._set("700.00")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.manual_amount_due)

    def test_other_fields_stay_read_only(self):
        self.client.put(
            f"/api/invoices/{self.invoice.pk}/manual-amount-due/",
            {"manual_amount_due": "700.00", "provider_name": "Чужой", "amount_due": "1.00"},
            format="json",
        )
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.provider_name)
        self.assertIsNone(self.invoice.amount_due)

    def test_unknown_amount_warning_hidden_while_manual_set(self):
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertIn("Сумма к оплате не распознана", detail["warnings"])
        self.assertNotIn("Сумма к оплате не распознана", self._set("700.00").data["warnings"])
        self.assertIn("Сумма к оплате не распознана", self._set(None).data["warnings"])


@override_settings(SECURE_SSL_REDIRECT=False)
class IncompleteExtractionTest(TestCase):
    """Разбор без единой услуги — неполный результат, а не «Обработан»."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="incomplete@example.com",
            email="incomplete@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSING,
        )

    def _process(self, parsed: dict) -> None:
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        # FieldFile.save(save=True) пишет весь инстанс — сначала подтягиваем свежий.
        self.invoice.refresh_from_db()
        self.invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        with patch("apps.invoices.tasks.parse_epd", return_value=parsed):
            process_invoice(self.invoice.pk)
        self.invoice.refresh_from_db()

    @staticmethod
    def _parsed(totals: dict, line_items: list[dict]) -> dict:
        return {
            "period": {"month": 1, "year": 2026, "start_date": None, "end_date": None},
            "totals": totals,
            "line_items": line_items,
            "warnings": [],
        }

    def test_known_amount_without_services_is_incomplete(self):
        self._process(self._parsed({"amount_due": "3600.00"}, []))

        self.assertEqual(self.invoice.status, Invoice.Status.INCOMPLETE)
        self.assertIn(NO_SERVICES_WARNING, self.invoice.warnings)
        # PDF и распознанные значения сохраняются
        self.assertEqual(self.invoice.amount_due, Decimal("3600.00"))
        self.assertTrue(self.invoice.pdf_file)

        self.client.force_authenticate(user=self.user)
        data = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertEqual(data["status"], "incomplete")
        self.assertIn(NO_SERVICES_WARNING, data["warnings"])

    def test_fully_empty_result_is_incomplete(self):
        self._process(self._parsed({}, []))

        self.assertEqual(self.invoice.status, Invoice.Status.INCOMPLETE)
        self.assertIn(NO_SERVICES_WARNING, self.invoice.warnings)
        self.assertIn("Сумма к оплате не распознана", self.invoice.warnings)

    def test_normal_invoice_stays_processed(self):
        self._process(
            self._parsed(
                {"amount_due": "100.00"},
                [{"service_name": "ОТОПЛЕНИЕ", "amount": "100.00"}],
            )
        )

        self.assertEqual(self.invoice.status, Invoice.Status.PROCESSED)
        self.assertNotIn(NO_SERVICES_WARNING, self.invoice.warnings)

    def test_successful_reparse_restores_processed(self):
        self._process(self._parsed({"amount_due": "3600.00"}, []))
        self.assertEqual(self.invoice.status, Invoice.Status.INCOMPLETE)

        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.PROCESSING, warnings=[]
        )
        self._process(
            self._parsed(
                {"amount_due": "3600.00"},
                [{"service_name": "ОТОПЛЕНИЕ", "amount": "3600.00"}],
            )
        )

        self.assertEqual(self.invoice.status, Invoice.Status.PROCESSED)
        self.assertNotIn(NO_SERVICES_WARNING, self.invoice.warnings)
        self.assertEqual(
            LineItem.objects.filter(invoice=self.invoice).count(), 1
        )

    @patch("apps.invoices.views.process_invoice.delay")
    def test_reparse_endpoint_allows_incomplete(self, mock_delay):
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.INCOMPLETE
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/invoices/{self.invoice.pk}/reparse/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once_with(self.invoice.pk)

    def test_existing_processed_without_services_marked_incomplete(self):
        import importlib

        migration = importlib.import_module(
            "apps.invoices.migrations.0012_invoice_incomplete_status"
        )
        from django.apps import apps as global_apps

        old_empty = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/old_empty.pdf",
            status=Invoice.Status.PROCESSED,
            amount_due=Decimal("3600.00"),
        )
        old_normal = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/old_normal.pdf",
            status=Invoice.Status.PROCESSED,
        )
        LineItem.objects.create(
            invoice=old_normal, service_name="ХВС", amount=Decimal("50.00")
        )

        migration.mark_incomplete_without_services(global_apps, None)

        old_empty.refresh_from_db()
        old_normal.refresh_from_db()
        self.assertEqual(old_empty.status, Invoice.Status.INCOMPLETE)
        self.assertIn(NO_SERVICES_WARNING, old_empty.warnings)
        # Распознанная сумма и PDF не тронуты
        self.assertEqual(old_empty.amount_due, Decimal("3600.00"))
        self.assertEqual(old_empty.pdf_file.name, "invoices/old_empty.pdf")
        self.assertEqual(old_normal.status, Invoice.Status.PROCESSED)
        self.assertNotIn(NO_SERVICES_WARNING, old_normal.warnings)


@override_settings(SECURE_SSL_REDIRECT=False)
class QueueRecoveryTest(TestCase):
    """Сбой постановки задачи не оставляет квитанцию в вечной обработке."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="queue@example.com",
            email="queue@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)

    def _upload(self):
        return self.client.post(
            "/api/invoices/upload/",
            {
                "pdf_file": SimpleUploadedFile(
                    "bill.pdf", FAKE_PDF, content_type="application/pdf"
                )
            },
            format="multipart",
        )

    @patch("apps.invoices.views.process_invoice.delay")
    def test_upload_queue_failure_returns_503_and_marks_failed(self, mock_delay):
        mock_delay.side_effect = OperationalError("broker down")

        response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], QUEUE_UNAVAILABLE_MESSAGE)
        invoice = Invoice.objects.get(user=self.user)
        self.assertEqual(invoice.status, Invoice.Status.FAILED)
        self.assertEqual(invoice.error_message, QUEUE_UNAVAILABLE_MESSAGE)
        self.assertTrue(invoice.pdf_file.name.endswith(".pdf"))

    @patch("apps.invoices.views.process_invoice.delay")
    def test_reparse_queue_failure_preserves_pdf_and_parsed_data(self, mock_delay):
        invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
            amount_due=Decimal("1500.00"),
            manual_amount_due=Decimal("700.00"),
            warnings=["старое предупреждение"],
        )
        mock_delay.side_effect = OperationalError("broker down")

        response = self.client.post(f"/api/invoices/{invoice.pk}/reparse/")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], QUEUE_UNAVAILABLE_MESSAGE)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.FAILED)
        self.assertEqual(invoice.error_message, QUEUE_UNAVAILABLE_MESSAGE)
        self.assertEqual(invoice.amount_due, Decimal("1500.00"))
        self.assertEqual(invoice.manual_amount_due, Decimal("700.00"))
        self.assertEqual(invoice.warnings, ["старое предупреждение"])
        self.assertEqual(invoice.pdf_file.name, "invoices/test.pdf")

    def test_reparse_after_queue_recovery_processes_same_invoice(self):
        from django.core.files.base import ContentFile

        from apps.invoices.tasks import process_invoice

        invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
        )
        with patch(
            "apps.invoices.views.process_invoice.delay",
            side_effect=OperationalError("broker down"),
        ):
            failed = self.client.post(f"/api/invoices/{invoice.pk}/reparse/")
        self.assertEqual(failed.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        with patch("apps.invoices.views.process_invoice.delay") as mock_delay:
            recovered = self.client.post(f"/api/invoices/{invoice.pk}/reparse/")

        self.assertEqual(recovered.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once_with(invoice.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PROCESSING)

        invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        parsed = {
            "period": {},
            "totals": {"amount_due": "900.00"},
            "line_items": [{"service_name": "ОТОПЛЕНИЕ", "amount": "900.00"}],
            "warnings": [],
        }
        with patch("apps.invoices.tasks.parse_epd", return_value=parsed):
            process_invoice(invoice.pk)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PROCESSED)
        self.assertEqual(invoice.amount_due, Decimal("900.00"))
        self.assertEqual(Invoice.objects.filter(user=self.user).count(), 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class CanReparseFlagTest(TestCase):
    """Флаг can_reparse повторяет правило и порог зависания из API."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="canreparse@example.com",
            email="canreparse@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/test.pdf",
            status=Invoice.Status.PROCESSED,
        )

    def _can_reparse(self):
        response = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["can_reparse"]

    def test_processed_incomplete_and_failed_allow_reparse(self):
        for state in (
            Invoice.Status.PROCESSED,
            Invoice.Status.INCOMPLETE,
            Invoice.Status.FAILED,
        ):
            Invoice.objects.filter(pk=self.invoice.pk).update(status=state)
            self.assertTrue(self._can_reparse(), state)

    def test_fresh_processing_forbids_reparse(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.PROCESSING
        )
        self.assertFalse(self._can_reparse())

    def test_stuck_processing_allows_reparse(self):
        from datetime import timedelta

        from django.utils import timezone

        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(minutes=10),
        )
        self.assertTrue(self._can_reparse())


UPLOAD_MEDIA_ROOT = tempfile.mkdtemp()
RACE_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=UPLOAD_MEDIA_ROOT)
class DuplicateUploadTest(TestCase):
    """Повторная загрузка того же PDF возвращает существующую квитанцию."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(UPLOAD_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(UPLOAD_MEDIA_ROOT, ignore_errors=True)
        os.makedirs(UPLOAD_MEDIA_ROOT, exist_ok=True)
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="dup@example.com",
            email="dup@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)

    def _upload(self, content: bytes = FAKE_PDF, name: str = "epd.pdf"):
        return self.client.post(
            "/api/invoices/upload/",
            {"pdf_file": SimpleUploadedFile(name, content, content_type="application/pdf")},
            format="multipart",
        )

    @patch("apps.invoices.views.process_invoice.delay")
    def test_same_content_returns_existing_invoice(self, mock_delay):
        first = self._upload()
        # Имя файла не определяет совпадение, только содержимое.
        second = self._upload(name="копия.pdf")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Invoice.objects.count(), 1)
        mock_delay.assert_called_once()

    @patch("apps.invoices.views.process_invoice.delay")
    def test_duplicate_does_not_leave_second_file(self, mock_delay):
        self._upload()
        self._upload(name="copy.pdf")

        _, filenames = default_storage.listdir("invoices/")
        self.assertEqual(len(filenames), 1)

    @patch("apps.invoices.views.process_invoice.delay")
    def test_retry_after_queue_failure_returns_failed_invoice(self, mock_delay):
        mock_delay.side_effect = OperationalError("broker down")
        first = self._upload()
        self.assertEqual(first.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        mock_delay.reset_mock()
        second = self._upload()

        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["id"], Invoice.objects.get(user=self.user).pk)
        self.assertEqual(second.data["status"], "failed")
        self.assertTrue(second.data["can_reparse"])
        mock_delay.assert_not_called()

    @patch("apps.invoices.views.process_invoice.delay")
    def test_different_users_get_separate_invoices(self, mock_delay):
        first = self._upload()
        other = User.objects.create_user(
            username="other-dup@example.com",
            email="other-dup@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=other)
        second = self._upload()

        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.data["id"], second.data["id"])
        self.assertEqual(Invoice.objects.count(), 2)
        own_ids = [i["id"] for i in self.client.get("/api/invoices/").data["results"]]
        self.assertEqual(own_ids, [second.data["id"]])

    @patch("apps.invoices.views.process_invoice.delay")
    def test_reupload_after_delete_creates_new_invoice(self, mock_delay):
        first = self._upload()
        pk = first.data["id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"/api/invoices/{pk}/")

        second = self._upload()

        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(second.data["id"], pk)
        self.assertEqual(Invoice.objects.count(), 1)

    @patch("apps.invoices.views.process_invoice.delay")
    def test_unfinished_invoice_reupload_allows_reparse(self, mock_delay):
        for index, state in enumerate(
            (Invoice.Status.FAILED, Invoice.Status.INCOMPLETE), start=1
        ):
            with self.subTest(state=state):
                content = FAKE_PDF + f"%{index}".encode()
                first = self._upload(content=content)
                Invoice.objects.filter(pk=first.data["id"]).update(status=state)

                second = self._upload(content=content)

                self.assertEqual(second.status_code, status.HTTP_200_OK)
                self.assertEqual(second.data["id"], first.data["id"])
                self.assertEqual(second.data["status"], state)
                self.assertTrue(second.data["can_reparse"])
                self.assertEqual(mock_delay.call_count, index * 2 - 1)

                response = self.client.post(
                    f"/api/invoices/{first.data['id']}/reparse/"
                )
                self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
                self.assertEqual(mock_delay.call_count, index * 2)

    def test_backfill_keeps_historical_duplicates(self):
        first = Invoice.objects.create(
            user=self.user, pdf_file=ContentFile(FAKE_PDF, name="old-a.pdf")
        )
        second = Invoice.objects.create(
            user=self.user, pdf_file=ContentFile(FAKE_PDF, name="old-b.pdf")
        )

        migration = import_module("apps.invoices.migrations.0013_invoice_content_hash")
        migration.fill_content_hash(global_apps, None)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.content_hash, FAKE_PDF_HASH)
        self.assertIsNone(second.content_hash)
        self.assertEqual(Invoice.objects.count(), 2)

    def test_db_blocks_second_invoice_with_same_content_hash(self):
        Invoice.objects.create(
            user=self.user, pdf_file="invoices/a.pdf", content_hash=FAKE_PDF_HASH
        )
        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                user=self.user, pdf_file="invoices/b.pdf", content_hash=FAKE_PDF_HASH
            )

    @patch("apps.invoices.views.process_invoice.delay")
    def test_raced_insert_returns_existing_and_cleans_file(self, mock_delay):
        # Проигравшая гонка: предварительный поиск промахнулся,
        # вставку отклонил уникальный индекс.
        existing = Invoice(user=self.user)
        existing.pdf_file.save("epd.pdf", ContentFile(FAKE_PDF), save=True)
        Invoice.objects.filter(pk=existing.pk).update(content_hash=FAKE_PDF_HASH)

        with patch.object(Invoice.objects, "filter", return_value=Invoice.objects.none()):
            response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], existing.pk)
        self.assertEqual(Invoice.objects.count(), 1)
        mock_delay.assert_not_called()
        _, filenames = default_storage.listdir("invoices/")
        self.assertEqual(filenames, [existing.pdf_file.name.rsplit("/", 1)[-1]])


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=RACE_MEDIA_ROOT)
@skipUnless(
    "postgresql" in settings.DATABASES["default"]["ENGINE"],
    "Конкурентную запись проверяем на PostgreSQL",
)
class ConcurrentDuplicateUploadTest(TransactionTestCase):
    """Параллельные загрузки одного PDF создают одну квитанцию."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(RACE_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(RACE_MEDIA_ROOT, ignore_errors=True)
        os.makedirs(RACE_MEDIA_ROOT, exist_ok=True)

    @patch("apps.invoices.views.process_invoice.delay")
    def test_parallel_uploads_create_one_invoice(self, mock_delay):
        user = User.objects.create_user(
            username="race@example.com",
            email="race@example.com",
            password="testpassword",
        )
        barrier = threading.Barrier(2)
        responses = []

        def worker(name: str) -> None:
            try:
                client = APIClient()
                client.force_authenticate(user=user)
                barrier.wait(timeout=10)
                responses.append(
                    client.post(
                        "/api/invoices/upload/",
                        {
                            "pdf_file": SimpleUploadedFile(
                                name, FAKE_PDF, content_type="application/pdf"
                            )
                        },
                        format="multipart",
                    )
                )
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(name,)) for name in ("a.pdf", "b.pdf")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(sorted(r.status_code for r in responses), [200, 201])
        self.assertEqual(len({r.data["id"] for r in responses}), 1)
        self.assertEqual(Invoice.objects.count(), 1)

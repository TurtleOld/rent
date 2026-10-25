from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import Invoice, LineItem, Service, ServiceAlias
from apps.invoices.validators import check_line_item

User = get_user_model()

FAKE_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


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
class PaymentTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="payer@example.com",
            email="payer@example.com",
            password="testpassword",
        )
        self.invoice = Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/fake.pdf",
            status=Invoice.Status.PROCESSED,
            amount_due=Decimal("1500.00"),
        )

    def test_payment_creation(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/invoices/{self.invoice.pk}/payments/",
            {"amount": "750.00", "payment_date": "2026-02-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["amount"], "750.00")

    def test_payment_rejects_non_positive_amount(self):
        self.client.force_authenticate(user=self.user)
        for amount in ("-500.00", "0.00"):
            response = self.client.post(
                f"/api/invoices/{self.invoice.pk}/payments/",
                {"amount": amount, "payment_date": "2026-02-01"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(self.invoice.payments.exists())

    def test_payment_status_partially_paid(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(
            f"/api/invoices/{self.invoice.pk}/payments/",
            {"amount": "750.00", "payment_date": "2026-02-01"},
            format="json",
        )
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "partially_paid")
        self.assertEqual(detail.data["total_paid"], Decimal("750.00"))

    def test_payment_status_paid(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(
            f"/api/invoices/{self.invoice.pk}/payments/",
            {"amount": "1500.00", "payment_date": "2026-02-01"},
            format="json",
        )
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "paid")

    def test_payment_status_unpaid(self):
        self.client.force_authenticate(user=self.user)
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "unpaid")

    def test_payment_status_paid_when_amount_due_is_zero(self):
        self.invoice.amount_due = Decimal("0.00")
        self.invoice.save(update_fields=["amount_due"])
        self.client.force_authenticate(user=self.user)
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "paid")

    def test_payment_status_paid_when_amount_due_is_negative(self):
        self.invoice.amount_due = Decimal("-1234.56")
        self.invoice.save(update_fields=["amount_due"])
        self.client.force_authenticate(user=self.user)
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "paid")

    def test_payment_status_amount_unknown_without_payments(self):
        self.invoice.amount_due = None
        self.invoice.save(update_fields=["amount_due"])
        self.client.force_authenticate(user=self.user)
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "amount_unknown")

    def test_payment_status_amount_unknown_with_payments(self):
        self.invoice.amount_due = None
        self.invoice.save(update_fields=["amount_due"])
        self.client.force_authenticate(user=self.user)
        self.client.post(
            f"/api/invoices/{self.invoice.pk}/payments/",
            {"amount": "750.00", "payment_date": "2026-02-01"},
            format="json",
        )
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(detail.data["payment_status"], "amount_unknown")
        self.assertEqual(detail.data["total_paid"], Decimal("750.00"))

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
        self.assertEqual(response.data["line_items"][0]["quantity"], "0.954318")


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


@override_settings(SECURE_SSL_REDIRECT=False)
class InvoiceListQueryCountTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="numqueries@example.com",
            email="numqueries@example.com",
            password="testpassword",
        )
        from apps.payments.models import Payment
        for i in range(3):
            inv = Invoice.objects.create(
                user=self.user,
                pdf_file=f"invoices/test{i}.pdf",
                status=Invoice.Status.PROCESSED,
                amount_due=Decimal("1000.00"),
            )
            Payment.objects.create(
                invoice=inv,
                user=self.user,
                amount=Decimal("500.00"),
                payment_date="2026-01-01",
            )

    def test_invoice_list_does_not_query_payments_per_invoice(self):
        self.client.force_authenticate(user=self.user)
        with self.assertNumQueries(3):
            response = self.client.get("/api/invoices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


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
        parsed = {"period": {}, "totals": totals, "line_items": [], "warnings": []}
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

    def test_manual_amount_turns_unknown_into_paid(self):
        self.invoice.payments.create(
            user=self.user, amount=Decimal("1000.00"), payment_date="2026-02-01"
        )
        detail = self.client.get(f"/api/invoices/{self.invoice.pk}/").data
        self.assertEqual(detail["payment_status"], "amount_unknown")

        response = self._set("1000.00")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["payment_status"], "paid")
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
            self.assertEqual(response.data["payment_status"], "paid")

    def test_more_than_two_decimals_rejected(self):
        response = self._set("10.005")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.manual_amount_due)

    def test_rejected_unless_processed(self):
        for state in (Invoice.Status.FAILED, Invoice.Status.PROCESSING):
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

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import Invoice, LineItem, Service, ServiceAlias

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

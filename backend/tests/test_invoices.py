from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import Invoice, LineItem

User = get_user_model()

FAKE_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


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

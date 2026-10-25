import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import Invoice

User = get_user_model()

FAKE_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA_ROOT)
class InvoicePdfCleanupTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="cleanup@example.com",
            email="cleanup@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)

    def _invoice(self) -> Invoice:
        invoice = Invoice(user=self.user, status=Invoice.Status.PROCESSED)
        invoice.pdf_file.save("test.pdf", ContentFile(FAKE_PDF), save=True)
        return invoice

    def test_api_delete_removes_pdf(self):
        invoice = self._invoice()
        name = invoice.pdf_file.name
        self.assertTrue(default_storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(default_storage.exists(name))

    def test_user_delete_removes_all_pdfs(self):
        names = [self._invoice().pdf_file.name for _ in range(2)]

        with self.captureOnCommitCallbacks(execute=True):
            self.user.delete()

        self.assertFalse(Invoice.objects.exists())
        for name in names:
            self.assertFalse(default_storage.exists(name))

    def test_rolled_back_delete_keeps_pdf(self):
        invoice = self._invoice()
        pk, name = invoice.pk, invoice.pdf_file.name

        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                invoice.delete()
                raise RuntimeError("откат")

        self.assertTrue(Invoice.objects.filter(pk=pk).exists())
        self.assertTrue(default_storage.exists(name))

    def test_missing_file_does_not_break_delete(self):
        invoice = self._invoice()
        default_storage.delete(invoice.pdf_file.name)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_storage_error_does_not_break_delete(self):
        invoice = self._invoice()

        with patch.object(default_storage, "delete", side_effect=OSError("диск")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.delete(f"/api/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())

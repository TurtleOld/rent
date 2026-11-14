import os
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.invoices.models import Invoice

User = get_user_model()

FAKE_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class CleanupOrphanPdfsTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="testpassword",
        )
        self.other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="testpassword",
        )

    def _invoice(self, user=None) -> Invoice:
        invoice = Invoice(user=user or self.user, status=Invoice.Status.PROCESSED)
        invoice.pdf_file.save("invoice.pdf", ContentFile(FAKE_PDF), save=True)
        return invoice

    def _orphan(self, filename: str = "orphan.pdf") -> str:
        return default_storage.save(f"invoices/{filename}", ContentFile(FAKE_PDF))

    def _age_file(self, name: str, hours: int) -> None:
        path = os.path.join(MEDIA_ROOT, name)
        timestamp = (timezone.now() - timedelta(hours=hours)).timestamp()
        os.utime(path, (timestamp, timestamp))

    def test_without_flag_lists_orphan_and_keeps_all_files(self):
        orphan = self._orphan()
        self._age_file(orphan, hours=2)
        invoice = self._invoice()
        existing = invoice.pdf_file.name
        self._age_file(existing, hours=2)

        stdout = StringIO()
        call_command("cleanup_orphan_pdfs", stdout=stdout)
        output = stdout.getvalue()

        self.assertIn("Осиротевшие файлы (1):", output)
        self.assertIn(orphan, output)
        self.assertNotIn(existing, output)
        self.assertTrue(default_storage.exists(orphan))
        self.assertTrue(default_storage.exists(existing))

    def test_delete_removes_orphan_and_keeps_existing_invoice_file(self):
        orphan = self._orphan()
        self._age_file(orphan, hours=2)
        existing = self._invoice().pdf_file.name
        self._age_file(existing, hours=2)

        stdout = StringIO()
        call_command("cleanup_orphan_pdfs", "--delete", stdout=stdout)
        output = stdout.getvalue()

        self.assertIn(orphan, output)
        self.assertFalse(default_storage.exists(orphan))
        self.assertTrue(default_storage.exists(existing))

    def test_recent_orphan_is_skipped_even_with_delete(self):
        orphan = self._orphan()
        self._age_file(orphan, hours=0)

        stdout = StringIO()
        call_command("cleanup_orphan_pdfs", stdout=stdout)

        self.assertNotIn(orphan, stdout.getvalue())
        self.assertTrue(default_storage.exists(orphan))

        stdout = StringIO()
        call_command("cleanup_orphan_pdfs", "--delete", stdout=stdout)

        self.assertNotIn(orphan, stdout.getvalue())
        self.assertTrue(default_storage.exists(orphan))

    def test_other_user_invoice_file_is_not_orphan(self):
        existing = self._invoice(user=self.other_user).pdf_file.name
        self._age_file(existing, hours=2)

        stdout = StringIO()
        call_command("cleanup_orphan_pdfs", "--delete", stdout=stdout)

        self.assertNotIn(existing, stdout.getvalue())
        self.assertTrue(default_storage.exists(existing))

    def test_delete_error_does_not_stop_other_files_and_returns_error(self):
        failed = self._orphan("failed.pdf")
        deleted = self._orphan("deleted.pdf")
        self._age_file(failed, hours=2)
        self._age_file(deleted, hours=2)
        real_delete = default_storage.delete

        def fake_delete(name: str) -> None:
            if name == failed:
                raise OSError("диск недоступен")
            real_delete(name)

        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.object(default_storage, "delete", side_effect=fake_delete),
            self.assertRaises(CommandError),
        ):
            call_command(
                "cleanup_orphan_pdfs", "--delete", stdout=stdout, stderr=stderr
            )

        self.assertIn(failed, stderr.getvalue())
        self.assertFalse(default_storage.exists(deleted))
        self.assertTrue(default_storage.exists(failed))

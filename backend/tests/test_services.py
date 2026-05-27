from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.invoices.models import Invoice, LineItem, Service, ServiceAlias

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class ServiceListTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="svclist@example.com",
            email="svclist@example.com",
            password="testpassword",
        )
        self.other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="testpassword",
        )

    def test_list_requires_auth(self):
        response = self.client.get("/api/services/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_only_own_services(self):
        Service.objects.create(user=self.user, canonical_name="ХВС")
        Service.objects.create(user=self.user, canonical_name="ГВС")
        Service.objects.create(user=self.other, canonical_name="ОТОПЛЕНИЕ")

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/services/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        names = [s["canonical_name"] for s in results]
        self.assertIn("ХВС", names)
        self.assertIn("ГВС", names)
        self.assertNotIn("ОТОПЛЕНИЕ", names)

    def test_list_includes_aliases(self):
        svc = Service.objects.create(user=self.user, canonical_name="ХВС")
        ServiceAlias.objects.create(service=svc, raw_name="ХОЛОДНАЯ ВОДА")
        ServiceAlias.objects.create(service=svc, raw_name="ХВС")

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/services/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        svc_data = results[0]
        raw_names = [a["raw_name"] for a in svc_data["aliases"]]
        self.assertIn("ХОЛОДНАЯ ВОДА", raw_names)
        self.assertIn("ХВС", raw_names)

    def test_list_empty_for_new_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/services/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(results, [])


@override_settings(SECURE_SSL_REDIRECT=False)
class ServiceTariffHistoryTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="tariff@example.com",
            email="tariff@example.com",
            password="testpassword",
        )
        self.other = User.objects.create_user(
            username="tariff_other@example.com",
            email="tariff_other@example.com",
            password="testpassword",
        )
        self.service = Service.objects.create(user=self.user, canonical_name="ХВС")

    def _make_invoice(self, year: int, month: int) -> Invoice:
        return Invoice.objects.create(
            user=self.user,
            pdf_file="invoices/fake.pdf",
            status=Invoice.Status.PROCESSED,
            period_year=year,
            period_month=month,
        )

    def test_history_requires_auth(self):
        response = self.client.get(f"/api/services/{self.service.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_history_forbidden_for_other_user(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get(f"/api/services/{self.service.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_returns_points_ordered_by_period(self):
        inv1 = self._make_invoice(2026, 1)
        inv2 = self._make_invoice(2026, 2)
        inv3 = self._make_invoice(2026, 3)
        LineItem.objects.create(invoice=inv1, service=self.service, service_name="ХВС", tariff=Decimal("50.00"), amount=Decimal("100.00"))
        LineItem.objects.create(invoice=inv2, service=self.service, service_name="ХВС", tariff=Decimal("55.00"), amount=Decimal("110.00"))
        LineItem.objects.create(invoice=inv3, service=self.service, service_name="ХВС", tariff=Decimal("55.00"), amount=Decimal("110.00"))

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/services/{self.service.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        points = response.data["points"]
        self.assertEqual(len(points), 3)
        self.assertEqual(points[0]["month"], 1)
        self.assertIsNone(points[0]["change_pct"])
        self.assertAlmostEqual(float(points[1]["change_pct"]), 10.0)
        self.assertAlmostEqual(float(points[2]["change_pct"]), 0.0)

    def test_history_empty_when_no_line_items(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/services/{self.service.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["points"], [])
        self.assertEqual(response.data["service"]["canonical_name"], "ХВС")

from django.test import TestCase

from apps.invoices.units import normalize_unit


class NormalizeUnitTest(TestCase):
    def test_sq_meter_dot(self):
        self.assertEqual(normalize_unit("кв.м."), "кв.м")

    def test_sq_meter_unicode(self):
        self.assertEqual(normalize_unit("м²"), "кв.м")

    def test_sq_meter_m2(self):
        self.assertEqual(normalize_unit("м2"), "кв.м")

    def test_cu_meter_dot(self):
        self.assertEqual(normalize_unit("куб.м."), "куб.м")

    def test_cu_meter_unicode(self):
        self.assertEqual(normalize_unit("м³"), "куб.м")

    def test_cu_meter_m3(self):
        self.assertEqual(normalize_unit("м3"), "куб.м")

    def test_sq_and_cu_are_different(self):
        self.assertNotEqual(normalize_unit("кв.м"), normalize_unit("куб.м"))

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize_unit("какая-то фигня"))

    def test_none_returns_none(self):
        self.assertIsNone(normalize_unit(None))

    def test_empty_returns_none(self):
        self.assertIsNone(normalize_unit(""))

    def test_kwh_latin(self):
        self.assertEqual(normalize_unit("kWh"), "кВт·ч")

    def test_whitespace_stripped(self):
        self.assertEqual(normalize_unit("  м2  "), "кв.м")

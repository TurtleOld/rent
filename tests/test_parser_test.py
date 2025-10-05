"""Tests for EPD parser functionality."""

from decimal import Decimal
from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import sys

import pytest


def _ensure_optional_dependencies() -> None:
    """Provide lightweight stubs for optional parser dependencies during tests."""
    if "pdfplumber" not in sys.modules:
        pdfplumber_stub = ModuleType("pdfplumber")
        pdfplumber_stub.open = lambda *args, **kwargs: None  # type: ignore[assignment]
        sys.modules["pdfplumber"] = pdfplumber_stub

    if "pdf2docx" not in sys.modules:
        pdf2docx_stub = ModuleType("pdf2docx")

        class _DummyConverter:  # pragma: no cover - simple stub
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def convert(self, *args: object, **kwargs: object) -> None:
                pass

            def close(self) -> None:
                pass

        pdf2docx_stub.Converter = _DummyConverter  # type: ignore[attr-defined]
        sys.modules["pdf2docx"] = pdf2docx_stub

    if "django" not in sys.modules:
        django_stub = ModuleType("django")
        sys.modules["django"] = django_stub

    if "django.core" not in sys.modules:
        django_core_stub = ModuleType("django.core")
        sys.modules["django.core"] = django_core_stub

    if "django.core.validators" not in sys.modules:
        django_validators_stub = ModuleType("django.core.validators")

        def _min_value_validator(value: object) -> object:  # pragma: no cover - stub
            return value

        django_validators_stub.MinValueValidator = _min_value_validator  # type: ignore[attr-defined]
        sys.modules["django.core.validators"] = django_validators_stub

    if "django.utils" not in sys.modules:
        django_utils_stub = ModuleType("django.utils")
        sys.modules["django.utils"] = django_utils_stub

    if "django.utils.translation" not in sys.modules:
        django_translation_stub = ModuleType("django.utils.translation")
        django_translation_stub.gettext_lazy = lambda value: value  # type: ignore[attr-defined]
        sys.modules["django.utils.translation"] = django_translation_stub

    if "django.db.models" not in sys.modules:
        django_models_stub = ModuleType("django.db.models")

        class _DummyField:  # pragma: no cover - simple stub
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

        class _DummyModel:  # pragma: no cover - simple stub
            def save(self, *args: object, **kwargs: object) -> None:
                pass

        class _DummyIndex:  # pragma: no cover - simple stub
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

        class _DummyForeignKey(_DummyField):  # pragma: no cover - simple stub
            def __class_getitem__(cls, item: object) -> type["_DummyForeignKey"]:
                return cls

        django_models_stub.Model = _DummyModel  # type: ignore[attr-defined]
        django_models_stub.CharField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.TextField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.DecimalField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.DateField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.DateTimeField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.PositiveIntegerField = _DummyField  # type: ignore[attr-defined]
        django_models_stub.ForeignKey = _DummyForeignKey  # type: ignore[attr-defined]
        django_models_stub.Index = _DummyIndex  # type: ignore[attr-defined]
        django_models_stub.CASCADE = object()

        sys.modules["django.db.models"] = django_models_stub

    if "django.db" not in sys.modules:
        django_db_stub = ModuleType("django.db")
        sys.modules["django.db"] = django_db_stub
    else:
        django_db_stub = sys.modules["django.db"]

    django_db_stub.models = sys.modules["django.db.models"]  # type: ignore[attr-defined]


_ensure_optional_dependencies()

pdf_parse_module = import_module("epd_parser.pdf_parse")
clean_amount = getattr(pdf_parse_module, "clean_amount")
EpdPdfParser = getattr(pdf_parse_module, "EpdPdfParser", None)
parse_services_data = getattr(pdf_parse_module, "parse_services_data")
parse_recalculation_table = getattr(
    pdf_parse_module, "parse_recalculation_table"
)


@pytest.mark.skipif(EpdPdfParser is None, reason="EpdPdfParser not available")
class TestEpdParser:
    """Test cases for EpdParser class."""

    def test_init_with_nonexistent_file(self) -> None:
        """Test initialization with non-existent file."""
        with pytest.raises(FileNotFoundError):
            EpdPdfParser(Path("nonexistent.pdf"))

    @patch("epd_parser.pdf_parse.pdfplumber.open")
    def test_parse_empty_pdf(self, mock_pdfplumber_open: Mock) -> None:
        """Test parsing empty PDF."""
        mock_pdf = Mock()
        mock_pdf.pages = []
        mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

        parser = EpdPdfParser(Path("test.pdf"))
        with pytest.raises(ValueError, match="No text content available"):
            parser.parse()

    @patch("epd_parser.pdf_parse.pdfplumber.open")
    def test_parse_valid_pdf(self, mock_pdfplumber_open: Mock) -> None:
        """Test parsing valid PDF with mock data."""
        # Mock PDF content
        mock_page = Mock()
        mock_page.extract_text.return_value = """
        ФИО: Иванов Иван Иванович
        Адрес: ул. Примерная, д. 1, кв. 1
        Лицевой счет: 123456789
        Расчетный период: 01.2024
        Срок оплаты: 25.01.2024
        Итого к оплате: 1500,00
        Итого с учетом страхования: 1550,00
        """

        mock_table = [
            ["Услуга", "Объем", "Тариф", "Сумма", "Долг", "Оплачено", "Итого"],
            ["Холодная вода", "5.000", "25.50", "127.50", "0.00", "0.00", "127.50"],
            ["Горячая вода", "3.000", "150.00", "450.00", "0.00", "0.00", "450.00"],
        ]

        mock_page.extract_tables.return_value = [mock_table]

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

        # Create a temporary file for testing
        test_file = Path("test.pdf")
        test_file.touch()

        try:
            parser = EpdPdfParser(test_file)
            result = parser.parse()

            # Verify the result structure
            assert "personal_info" in result
            assert "payment_info" in result
            assert "service_charges" in result
            assert "totals" in result

            # Verify personal info
            personal_info = result["personal_info"]
            assert personal_info["full_name"] == "Иванов Иван Иванович"
            assert personal_info["account_number"] == "123456789"

            # Verify payment info
            payment_info = result["payment_info"]
            assert payment_info["payment_period"] == "01.2024"

            # Verify service charges
            service_charges = result["service_charges"]
            expected_service_count = 2
            assert len(service_charges) == expected_service_count

            # Verify totals
            totals = result["totals"]
            assert totals["total_without_insurance"] == Decimal("1500.00")
            assert totals["total_with_insurance"] == Decimal("1550.00")

        finally:
            test_file.unlink(missing_ok=True)

    def test_parse_decimal_valid(self) -> None:
        """Test decimal parsing with valid values."""
        parser = EpdPdfParser(Path("test.pdf"))

        # Test different decimal formats
        assert parser._parse_decimal("1500,00") == Decimal("1500.00")
        assert parser._parse_decimal("1,234.56") == Decimal("1234.56")
        assert parser._parse_decimal("1234.56") == Decimal("1234.56")
        assert parser._parse_decimal("0") == Decimal("0")

    def test_parse_decimal_invalid(self) -> None:
        """Test decimal parsing with invalid values."""
        parser = EpdPdfParser(Path("test.pdf"))

        # Test invalid values
        assert parser._parse_decimal("") is None
        assert parser._parse_decimal("abc") is None
        assert parser._parse_decimal("1,234,567.89") is None  # Too many commas



def test_clean_amount_fragment_selection() -> None:
    """Ensure clean_amount picks the most relevant numeric fragment."""
    multiline_value = "0,00\n1\u00a0243,09"
    trailing_minus_value = "202,85-"

    assert clean_amount(multiline_value) == Decimal("1243.09")
    assert clean_amount(trailing_minus_value) == Decimal("-202.85")


def test_parse_services_data_resolves_signs_from_fragments() -> None:
    """Ensure recalculation and debt columns respect implicit minus values."""

    table_data = [
        [
            "Начисления за коммунальные услуги",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "Виды услуг",
            "Объем",
            "Ед.",
            "Тариф",
            "Начислено",
            "Перерасчеты (начисления, уменьшения)",
            "Задолженность (Переплата (-))",
            "Оплачено",
            "Итого",
        ],
        [
            "ГОРЯЧЕЕ В/С (ЭНЕРГИЯ) ОДН",
            "0,000",
            "Гкал",
            "0,00",
            "0,00",
            "0,00\n1\u00a0243,09",
            "0,00\n1\u00a0243,09",
            "0,00",
            "0,00",
        ],
    ]

    services = parse_services_data(table_data)
    assert "Начисления за коммунальные услуги" in services
    service_entry = services["Начисления за коммунальные услуги"][0]

    assert service_entry["recalculation"] == Decimal("-1243.09")
    assert service_entry["debt"] == Decimal("-1243.09")


def test_parse_recalculation_table_extracts_entries() -> None:
    """Validate recalculation parsing from dedicated tables."""

    table_data = [
        ["Перерасчеты"],
        ["Вид услуги", "Период", "Основание", "Сумма"],
        [
            "Горячее водоснабжение",
            "08.2025",
            "Корректировка показаний",
            "202,85-",
        ],
        [
            "Холодное водоснабжение",
            "07.2025",
            "Доначисление",
            "150,00",
        ],
        ["Итого", "", "", "52,85"],
    ]

    recalculations = parse_recalculation_table(table_data)

    assert recalculations == [
        {
            "service_name": "Горячее водоснабжение",
            "reason": "08.2025; Корректировка показаний",
            "amount": Decimal("-202.85"),
        },
        {
            "service_name": "Холодное водоснабжение",
            "reason": "07.2025; Доначисление",
            "amount": Decimal("150.00"),
        },
    ]

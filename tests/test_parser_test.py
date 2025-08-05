"""Tests for EPD parser functionality."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from epd_parser.pdf_parse import EpdPdfParser  # type: ignore


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

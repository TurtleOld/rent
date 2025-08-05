"""Django forms for EPD parser application."""

import logging
import re
from typing import Any, cast

from django import forms
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.utils.translation import gettext_lazy as _

from .pdf_parse import parse_epd_pdf

logger = logging.getLogger(__name__)


class EpdDocumentForm(forms.Form):
    """Form for editing EPD document data without pdf_file field."""

    full_name = forms.CharField(
        max_length=255,
        label=_("Full Name"),
        help_text=_("Full name of the person responsible for payments"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Enter full name"),
            }
        ),
    )
    address = forms.CharField(
        label=_("Address"),
        help_text=_("Full address of the property"),
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _("Enter full address"),
            }
        ),
    )
    account_number = forms.CharField(
        max_length=50,
        label=_("Account Number"),
        help_text=_("Unique account number for the property"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Enter account number"),
            }
        ),
    )
    payment_period = forms.CharField(
        max_length=20,
        label=_("Payment Period"),
        help_text=_('Payment period (e.g., "01.2024")'),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("e.g., 01.2024"),
            }
        ),
    )
    due_date = forms.DateField(
        label=_("Due Date"),
        help_text=_("Payment due date"),
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )
    total_without_insurance = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label=_("Total Without Insurance"),
        help_text=_("Total amount without insurance"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }
        ),
    )
    total_with_insurance = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label=_("Total With Insurance"),
        help_text=_("Total amount including insurance"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }
        ),
    )

    parsed_data = None  # Will store parsed PDF data for reference

    def _prefill_with_parsed_data(self) -> None:
        """Pre-fill form fields with parsed data."""
        personal_info: dict[str, Any] = (
            self.parsed_data.get("personal_info", {}) if self.parsed_data else {}
        )
        payment_info: dict[str, Any] = (
            self.parsed_data.get("payment_info", {}) if self.parsed_data else {}
        )
        totals: dict[str, Any] = (
            self.parsed_data.get("totals", {}) if self.parsed_data else {}
        )

        # Create initial data dictionary
        initial_data = {}

        # Pre-fill personal information
        if "full_name" in personal_info:
            initial_data["full_name"] = personal_info["full_name"]

        if "address" in personal_info:
            initial_data["address"] = personal_info["address"]

        if "account_number" in personal_info:
            initial_data["account_number"] = personal_info["account_number"]

        # Pre-fill payment information
        if "payment_period" in payment_info:
            initial_data["payment_period"] = payment_info["payment_period"]
        elif "period" in payment_info:
            initial_data["payment_period"] = payment_info["period"]
        elif "period" in personal_info:
            initial_data["payment_period"] = personal_info["period"]
        else:
            # Try to extract from text content
            period_match = re.search(
                r"([а-яё]+)\s+([0-9]{4})",
                self.parsed_data.get("text_content", "") if self.parsed_data else "",
            )
            if period_match:
                month, year = period_match.groups()
                initial_data["payment_period"] = f"{month} {year}"

        if "due_date" in payment_info:
            try:
                # Convert date string to DateField format
                due_date = payment_info["due_date"]
                if re.match(r"\d{4}-\d{2}-\d{2}", due_date):
                    initial_data["due_date"] = due_date
                elif re.match(r"\d{2}\.\d{2}\.\d{4}", due_date):
                    day, month, year = due_date.split(".")
                    initial_data["due_date"] = f"{year}-{month}-{day}"
            except (ValueError, TypeError):
                pass

        # Pre-fill financial totals
        if "total_without_insurance" in totals:
            initial_data["total_without_insurance"] = totals["total_without_insurance"]

        if "total_with_insurance" in totals:
            initial_data["total_with_insurance"] = totals["total_with_insurance"]

        # Calculate insurance amount if not provided
        if (
            "insurance_amount" not in totals
            and "total_with_insurance" in totals
            and "total_without_insurance" in totals
        ):
            insurance_amount = (
                totals["total_with_insurance"] - totals["total_without_insurance"]
            )
            if insurance_amount > 0:
                initial_data["insurance_amount"] = insurance_amount

        # Set initial data
        self.initial = initial_data

    def clean_account_number(self) -> str:
        """Validate account number format."""
        account_number = self.cleaned_data.get("account_number")

        if account_number:
            # Remove any non-digit characters
            cleaned_number = "".join(filter(str.isdigit, account_number))

            if not cleaned_number:
                raise ValidationError(
                    _("Account number must contain at least one digit.")
                )

            return cleaned_number

        return account_number or ""

    def clean(self) -> dict[str, Any]:
        """Clean and validate form data."""
        cleaned_data = super().clean()

        # If POST data is missing required fields, use initial data
        if not self.data or len(self.data) <= 1:  # Only CSRF token
            for field_name in self.fields:
                if field_name not in cleaned_data and field_name in self.initial:
                    cleaned_data[field_name] = self.initial[field_name]

        # Validate that total with insurance is greater than or equal to total without insurance
        total_without = cleaned_data.get("total_without_insurance")
        total_with = cleaned_data.get("total_with_insurance")

        if total_without and total_with and total_with < total_without:
            raise ValidationError(
                _("Total with insurance cannot be less than total without insurance.")
            )

        return cast(dict[str, Any], cleaned_data)

    def is_valid(self) -> bool:
        """Override is_valid to use initial data when POST data is missing."""
        # If we have initial data but no POST data (or only CSRF token), use initial data
        if self.initial and (not self.data or len(self.data) <= 1):
            # Create a copy of initial data as POST data
            initial_data = QueryDict("", mutable=True)
            for key, value in self.initial.items():
                initial_data[key] = str(value)
            # Add CSRF token if present
            if self.data and "csrfmiddlewaretoken" in self.data:
                initial_data["csrfmiddlewaretoken"] = self.data["csrfmiddlewaretoken"]
            # Use _data attribute to bypass the property
            self._data = initial_data

        return super().is_valid()  # type: ignore


class PdfUploadForm(forms.Form):
    """Form for uploading PDF files."""

    pdf_file = forms.FileField(
        label=_("PDF File"),
        help_text=_("Select a PDF file to upload and parse"),
        widget=forms.FileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf",
            }
        ),
    )

    def clean_pdf_file(self) -> Any:
        """Validate PDF file."""
        pdf_file = self.cleaned_data.get("pdf_file")

        if pdf_file:
            # Check file extension
            if not pdf_file.name.lower().endswith(".pdf"):
                raise ValidationError(_("Only PDF files are allowed."))

            # Check file size (10MB limit)
            if pdf_file.size > 10 * 1024 * 1024:
                raise ValidationError(_("File size must be less than 10MB."))

            # Try to parse the PDF to validate it's a valid EPD document
            try:
                pdf_file.seek(0)  # Reset file pointer
                logger.info(f"Parsing PDF file: {pdf_file.name}")
                parsed_data = parse_epd_pdf(pdf_file)

                # Store parsed data for later use
                self.parsed_data = parsed_data

                # Validate that we have required data
                if not parsed_data.get("personal_info", {}).get("account_number"):
                    logger.error("No account number found in parsed data")
                    raise ValidationError(
                        _(
                            "Could not extract account number from PDF. Please ensure this is a valid EPD document."
                        )
                    )

                logger.info(
                    f"Successfully parsed PDF with account number: {parsed_data.get('personal_info', {}).get('account_number')}"
                )

            except Exception as e:
                logger.error(f"Error parsing PDF: {e!s}")
                raise ValidationError(
                    _(
                        "Error parsing PDF file. Please ensure this is a valid EPD document."
                    )
                ) from e

        return pdf_file

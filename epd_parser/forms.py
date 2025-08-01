"""Django forms for EPD parser application."""

import logging
from pathlib import Path
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import EpdDocument
from .parser import EpdParser, EpdParserError
from .ocr_parser import OcrEpdParser, OcrEpdParserError

logger = logging.getLogger(__name__)


class EpdUploadForm(forms.ModelForm):
    """Form for uploading EPD PDF files."""
    
    class Meta:
        """Meta options for EpdUploadForm."""
        
        model = EpdDocument
        fields = ['pdf_file']
        widgets = {
            'pdf_file': forms.FileInput(
                attrs={
                    'class': 'form-control',
                    'accept': '.pdf',
                    'aria-describedby': 'pdfHelp',
                }
            ),
        }
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the form with custom help text."""
        super().__init__(*args, **kwargs)
        self.fields['pdf_file'].help_text = _(
            'Upload an EPD (Unified Payment Document) PDF file. '
            'The file will be automatically parsed and data will be extracted.'
        )
        self.fields['pdf_file'].label = _('EPD PDF File')
    
    def clean_pdf_file(self) -> Any:
        """Validate the uploaded PDF file.
        
        Returns:
            The cleaned PDF file
            
        Raises:
            ValidationError: If the file is invalid
        """
        pdf_file = self.cleaned_data.get('pdf_file')
        
        if not pdf_file:
            raise ValidationError(_('Please select a PDF file to upload.'))
        
        # Check file extension
        file_extension = Path(pdf_file.name).suffix.lower()
        if file_extension != '.pdf':
            raise ValidationError(_('Only PDF files are allowed.'))
        
        # Check file size (10MB limit)
        if pdf_file.size > 10 * 1024 * 1024:
            raise ValidationError(_('File size must be less than 10MB.'))
        
        # Try to parse the PDF to validate it's a valid EPD document
        try:
            # Save the file temporarily to parse it
            temp_path = Path('/tmp') / f'epd_temp_{pdf_file.name}'
            with open(temp_path, 'wb') as f:
                for chunk in pdf_file.chunks():
                    f.write(chunk)
            
            # Try to parse the PDF using OCR first, fallback to regular parser
            parsed_data = None
            parser_error = None
            
            try:
                # Try OCR parser first
                ocr_parser = OcrEpdParser(temp_path)
                parsed_data = ocr_parser.parse()
                logger.info("Successfully parsed PDF using OCR")
            except OcrEpdParserError as e:
                logger.warning(f"OCR parsing failed: {e}")
                parser_error = e
                
                # Fallback to regular parser
                try:
                    parser = EpdParser(temp_path)
                    parsed_data = parser.parse()
                    logger.info("Successfully parsed PDF using regular parser")
                except EpdParserError as e2:
                    logger.error(f"Regular parsing also failed: {e2}")
                    raise ValidationError(_('Failed to parse the PDF file using both OCR and regular methods. Please ensure it is a valid EPD document.'))
            
            # Validate that we got some data
            if not parsed_data.get('personal_info') and not parsed_data.get('full_name') and not parsed_data.get('account_number'):
                raise ValidationError(_('Could not extract personal information from the PDF.'))
            
            if not parsed_data.get('service_charges'):
                raise ValidationError(_('Could not extract service charges from the PDF.'))
            
            # Store parsed data in the form for later use
            self.parsed_data = parsed_data
            
            # Clean up temporary file
            temp_path.unlink(missing_ok=True)
            
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during PDF validation: {e}")
            raise ValidationError(_('An error occurred while processing the PDF file.'))
        
        return pdf_file


class EpdDocumentForm(forms.ModelForm):
    """Form for editing EPD document data."""
    
    class Meta:
        """Meta options for EpdDocumentForm."""
        
        model = EpdDocument
        fields = [
            'full_name',
            'address',
            'account_number',
            'payment_period',
            'due_date',
            'total_without_insurance',
            'total_with_insurance',
        ]
        widgets = {
            'full_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Enter full name'),
                }
            ),
            'address': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': _('Enter full address'),
                }
            ),
            'account_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Enter account number'),
                }
            ),
            'payment_period': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('e.g., 01.2024'),
                }
            ),
            'due_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'total_without_insurance': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                }
            ),
            'total_with_insurance': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                }
            ),
        }
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the form with parsed data if available."""
        self.parsed_data = kwargs.pop('parsed_data', None)
        super().__init__(*args, **kwargs)
        
        # Pre-fill form with parsed data if available
        if self.parsed_data and not self.instance.pk:
            self._prefill_with_parsed_data()
    
    def _prefill_with_parsed_data(self) -> None:
        """Pre-fill form fields with parsed data."""
        personal_info = self.parsed_data.get('personal_info', {})
        payment_info = self.parsed_data.get('payment_info', {})
        totals = self.parsed_data.get('totals', {})
        
        logger.info(f"Pre-filling form with parsed data:")
        logger.info(f"Personal info: {personal_info}")
        logger.info(f"Payment info: {payment_info}")
        logger.info(f"Totals: {totals}")
        
        # Create initial data dictionary
        initial_data = {}
        
        # Pre-fill personal information
        if 'full_name' in personal_info:
            initial_data['full_name'] = personal_info['full_name']
            logger.info(f"Setting full_name: {personal_info['full_name']}")
        
        if 'address' in personal_info:
            initial_data['address'] = personal_info['address']
            logger.info(f"Setting address: {personal_info['address']}")
        
        if 'account_number' in personal_info:
            initial_data['account_number'] = personal_info['account_number']
            logger.info(f"Setting account_number: {personal_info['account_number']}")
        
        # Pre-fill payment information
        if 'payment_period' in payment_info:
            initial_data['payment_period'] = payment_info['payment_period']
            logger.info(f"Setting payment_period: {payment_info['payment_period']}")
        
        if 'due_date' in payment_info:
            # Convert date from DD.MM.YYYY to YYYY-MM-DD format
            try:
                from datetime import datetime
                date_obj = datetime.strptime(payment_info['due_date'], '%d.%m.%Y')
                initial_data['due_date'] = date_obj.strftime('%Y-%m-%d')
                logger.info(f"Setting due_date: {initial_data['due_date']}")
            except (ValueError, TypeError):
                # If conversion fails, use original value
                initial_data['due_date'] = payment_info['due_date']
                logger.info(f"Setting due_date (original): {payment_info['due_date']}")
        
        # Pre-fill totals
        if 'total_without_insurance' in totals:
            initial_data['total_without_insurance'] = totals['total_without_insurance']
            logger.info(f"Setting total_without_insurance: {totals['total_without_insurance']}")
        
        if 'total_with_insurance' in totals:
            initial_data['total_with_insurance'] = totals['total_with_insurance']
            logger.info(f"Setting total_with_insurance: {totals['total_with_insurance']}")
        
        # Set initial data
        self.initial = initial_data
        
        logger.info(f"Final initial data: {initial_data}")
    
    def clean_account_number(self) -> str:
        """Validate account number format."""
        account_number = self.cleaned_data.get('account_number')
        
        if account_number:
            # Remove any non-digit characters
            cleaned_number = ''.join(filter(str.isdigit, account_number))
            
            if not cleaned_number:
                raise ValidationError(_('Account number must contain at least one digit.'))
            
            return cleaned_number
        
        return account_number
    
    def clean(self) -> dict[str, Any]:
        """Clean and validate form data."""
        cleaned_data = super().clean()
        
        # Validate that total with insurance is greater than or equal to total without insurance
        total_without = cleaned_data.get('total_without_insurance')
        total_with = cleaned_data.get('total_with_insurance')
        
        if total_without and total_with and total_with < total_without:
            raise ValidationError(
                _('Total with insurance cannot be less than total without insurance.')
            )
        
        return cleaned_data 
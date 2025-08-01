"""PDF parser for EPD (Unified Payment Document) using GitHub Models API with structured data extraction."""

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class OcrEpdParserError(Exception):
    """Custom exception for EPD parsing errors with OCR."""
    
    pass


class OcrEpdParser:
    """Parser for EPD (Unified Payment Document) PDF files using GitHub Models API with structured data extraction.
    
    This parser uses GPT-4o to directly extract structured data from PDF images, avoiding the need
    for complex regex pattern matching on OCR text.
    """
    
    def __init__(self, pdf_path: Path) -> None:
        """Initialize the parser with a PDF file path.
        
        Args:
            pdf_path: Path to the PDF file to parse
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise OcrEpdParserError(f"PDF file not found: {pdf_path}")
        
        self._text_content: Optional[str] = None
        self._tables: Optional[List[List[List[str]]]] = None
    
    def parse(self) -> Dict[str, Any]:
        """Parse the EPD PDF and return structured data.
        
        Returns:
            Dictionary containing parsed EPD data
            
        Raises:
            OcrEpdParserError: If parsing fails
        """
        try:
            # Extract structured data using OCR API
            extracted_data = self._extract_structured_data_with_ocr()
            
            # Convert the extracted data to the expected format
            personal_info = extracted_data.get('personal_info', {})
            service_charges = self._convert_service_charges(extracted_data.get('service_charges', []))
            totals = extracted_data.get('totals', {})
            
            # Create payment_info from personal_info
            payment_info = {
                'period': personal_info.get('period', ''),
                'due_date': personal_info.get('due_date', ''),
            }
            
            # Validate totals - they should be reasonable final amounts
            if totals:
                total_without = totals.get('total_without_insurance', 0)
                total_with = totals.get('total_with_insurance', 0)
                
                # Check if totals look like intermediate sums rather than final amounts
                if total_without > 0 and total_with > 0:
                    # If the difference is very small, they might be the same value
                    if abs(total_with - total_without) < 10:
                        logger.warning(f"Totals look suspiciously similar: {total_without} vs {total_with}")
                    
                    # Log the extracted totals for debugging
                    logger.info(f"Extracted totals - without insurance: {total_without}, with insurance: {total_with}")
            
            return {
                'personal_info': personal_info,
                'payment_info': payment_info,
                'service_charges': service_charges,
                'totals': totals,
            }
            
        except Exception as e:
            logger.error(f"Error parsing PDF {self.pdf_path}: {e}")
            raise OcrEpdParserError(f"Failed to parse PDF: {e}") from e
    
    def _extract_structured_data_with_ocr(self) -> Dict[str, Any]:
        """Extract structured data using GitHub Models API with GPT-4o.
        
        Returns:
            Extracted structured data as dictionary
        """
        try:
            from django.conf import settings
            from openai import OpenAI
            import fitz  # PyMuPDF
            import base64
            import io
            from PIL import Image
            
            # GitHub Models API configuration
            api_token = getattr(settings, 'GITHUB_MODELS_API_TOKEN', '')
            api_url = getattr(settings, 'GITHUB_MODELS_BASE_URL', 'https://models.github.ai/inference')
            
            if not api_token:
                raise OcrEpdParserError("GitHub Models API token not configured")
            
            # Open PDF and convert pages to images
            pdf_document = fitz.open(self.pdf_path)
            images = []
            
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                # Render page to image with higher resolution
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                images.append(img_data)
            
            pdf_document.close()
            
            # Create OpenAI client with GitHub Models endpoint
            client = OpenAI(
                base_url=api_url,
                api_key=api_token,
            )
            
            # Prepare the prompt for structured data extraction
            prompt = """This is a Russian utility payment document (ЕПД - Единый Платёжный Документ). 

Please extract the following structured data from this document and return it as a valid JSON object:

1. Personal Information:
   - account_number: Account number
   - address: Full address
   - period: Billing period (e.g., "июль 2025")
   - due_date: Payment due date

2. Service Charges (array of objects):
   Each service should have:
   - service_name: Name of the service (e.g., "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ", "ВОДООТВЕДЕНИЕ ОДН")
   - volume: Volume of service consumed (numeric)
   - tariff: Tariff rate per unit (numeric)
   - amount: Amount calculated by tariff (numeric)
   - recalculations: Recalculation amount (numeric)
   - debt: Debt amount (numeric)
   - paid: Amount paid (numeric)
   - total: Total amount (numeric)

3. Totals:
   - total_without_insurance: "Итого к оплате" without voluntary insurance (final amount to pay)
   - total_with_insurance: "Итого к оплате" with voluntary insurance (final amount to pay)

Important:
- Extract ALL services from the table, including ODN services
- Use exact service names as they appear in the document
- All numeric values should be numbers (not strings)
- If a value is missing or zero, use 0
- For totals, look specifically for "Итого к оплате" amounts, NOT intermediate sums
- The totals should be the final amounts that the customer needs to pay
- Return ONLY valid JSON, no additional text or explanations

Example format:
{
  "personal_info": {
    "full_name": "Иванов Иван Иванович",
    "account_number": "123456789",
    "address": "ул. Примерная, д. 1, кв. 1",
    "period": "июль 2025",
    "due_date": "25.08.2025"
  },
  "service_charges": [
    {
      "service_name": "ВЗНОС НА КАПИТАЛЬНЫЙ РЕМОНТ",
      "volume": 68.9,
      "tariff": 1515.8,
      "amount": 0,
      "recalculations": 0,
      "debt": 1240.2,
      "paid": 1240.2,
      "total": 0
    }
  ],
  "totals": {
    "total_without_insurance": 9584.28,
    "total_with_insurance": 9873.66
  }
}"""

            # Process all pages and extract structured data
            all_data = []
            
            for i, img_data in enumerate(images):
                # Convert image data to base64
                img_base64 = base64.b64encode(img_data).decode('utf-8')
                
                # Make API request for this page
                response = client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"{prompt}\n\nThis is page {i+1} of the document."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{img_base64}",
                                        "detail": "high"
                                    }
                                }
                            ]
                        }
                    ],
                    model="openai/gpt-4o",
                    max_tokens=4000,
                    temperature=0.1
                )
                
                # Extract JSON from response
                page_content = response.choices[0].message.content.strip()
                logger.info(f"Received response from page {i+1}: {len(page_content)} characters")
                
                try:
                    # Try to parse JSON from the response
                    page_data = json.loads(page_content)
                    all_data.append(page_data)
                    logger.info(f"Successfully parsed JSON from page {i+1}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON from page {i+1}: {e}")
                    logger.debug(f"Raw response: {page_content}")
                    
                    # Try to extract JSON from markdown code blocks
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', page_content, re.DOTALL)
                    if json_match:
                        try:
                            page_data = json.loads(json_match.group(1))
                            all_data.append(page_data)
                            logger.info(f"Successfully extracted JSON from markdown code block on page {i+1}")
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse JSON from markdown code block on page {i+1}")
                    
                    # If markdown extraction fails, try to extract JSON from the text
                    if not json_match:
                        json_match = re.search(r'\{.*\}', page_content, re.DOTALL)
                        if json_match:
                            try:
                                page_data = json.loads(json_match.group(0))
                                all_data.append(page_data)
                                logger.info(f"Successfully extracted JSON from page {i+1} using regex")
                            except json.JSONDecodeError:
                                logger.error(f"Failed to extract JSON from page {i+1} even with regex")
            
            # Merge data from all pages
            if not all_data:
                raise OcrEpdParserError("No valid JSON data extracted from any page")
            
            # Combine data from all pages
            combined_data = self._merge_page_data(all_data)
            logger.info(f"Successfully extracted structured data using GitHub Models API")
            return combined_data
            
        except Exception as e:
            logger.error(f"GitHub Models API extraction failed: {e}")
            raise OcrEpdParserError(f"GitHub Models API extraction failed: {e}")
    
    def _merge_page_data(self, page_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge data from multiple pages into a single structure.
        
        Args:
            page_data_list: List of data dictionaries from each page
            
        Returns:
            Merged data structure
        """
        if not page_data_list:
            return {}
        
        if len(page_data_list) == 1:
            return page_data_list[0]
        
        # Start with the first page's data
        merged_data = page_data_list[0].copy()
        
        # Merge service charges from all pages
        all_service_charges = []
        for page_data in page_data_list:
            if 'service_charges' in page_data and isinstance(page_data['service_charges'], list):
                all_service_charges.extend(page_data['service_charges'])
        
        # Remove duplicates based on service name
        seen_services = set()
        unique_service_charges = []
        for service in all_service_charges:
            service_name = service.get('service_name', '')
            if service_name and service_name not in seen_services:
                seen_services.add(service_name)
                unique_service_charges.append(service)
        
        merged_data['service_charges'] = unique_service_charges
        
        # Merge totals (take the highest values)
        if 'totals' in merged_data:
            for page_data in page_data_list:
                if 'totals' in page_data:
                    for key, value in page_data['totals'].items():
                        if key in merged_data['totals']:
                            # Take the higher value for totals
                            if isinstance(value, (int, float)) and isinstance(merged_data['totals'][key], (int, float)):
                                merged_data['totals'][key] = max(merged_data['totals'][key], value)
                        else:
                            merged_data['totals'][key] = value
        
        logger.info(f"Merged data from {len(page_data_list)} pages: {len(unique_service_charges)} unique services")
        return merged_data
    
    def _convert_service_charges(self, extracted_services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert extracted service charges to the expected format.
        
        Args:
            extracted_services: List of service dictionaries from OCR
            
        Returns:
            List of service charge dictionaries in expected format
        """
        converted_services = []
        
        for i, service in enumerate(extracted_services):
            try:
                # Convert numeric values to Decimal
                volume = self._convert_to_decimal(service.get('volume', 0))
                tariff = self._convert_to_decimal(service.get('tariff', 0))
                amount = self._convert_to_decimal(service.get('amount', 0))
                recalculations = self._convert_to_decimal(service.get('recalculations', 0))
                debt = self._convert_to_decimal(service.get('debt', 0))
                paid = self._convert_to_decimal(service.get('paid', 0))
                total = self._convert_to_decimal(service.get('total', 0))
                
                converted_service = {
                    'service_name': service.get('service_name', ''),
                    'volume': volume,
                    'tariff': tariff,
                    'amount': amount,
                    'debt': debt,
                    'paid': paid,
                    'total': total,
                    'order': i,
                }
                
                converted_services.append(converted_service)
                logger.info(f"Converted service: {converted_service['service_name']} - volume={volume}, tariff={tariff}, amount={amount}, debt={debt}, paid={paid}, total={total}")
                
            except Exception as e:
                logger.warning(f"Failed to convert service {service.get('service_name', 'Unknown')}: {e}")
                continue
        
        logger.info(f"Converted {len(converted_services)} services")
        return converted_services
    
    def _convert_to_decimal(self, value: Any) -> Decimal:
        """Convert a value to Decimal.
        
        Args:
            value: Value to convert (can be int, float, string, or Decimal)
            
        Returns:
            Decimal value
        """
        if isinstance(value, Decimal):
            return value
        elif isinstance(value, (int, float)):
            return Decimal(str(value))
        elif isinstance(value, str):
            return self._parse_decimal(value) or Decimal('0.00')
        else:
            return Decimal('0.00')
    
    def _parse_decimal(self, value_str: str) -> Optional[Decimal]:
        """Parse a string value to Decimal with improved handling of various formats.
        
        Args:
            value_str: String value to parse
            
        Returns:
            Decimal value or None if parsing fails
        """
        if not value_str:
            return None
        
        # Clean the string - remove all non-numeric characters except , and .
        cleaned = re.sub(r'[^\d,\.]', '', value_str.strip())
        
        # Handle various number formats
        if not cleaned:
            return None
        
        # Handle Russian number format with spaces (e.g., "1 234,56")
        if ' ' in cleaned:
            cleaned = cleaned.replace(' ', '')
        
        # Handle decimal separators
        if ',' in cleaned and '.' in cleaned:
            # If both separators present, assume comma is thousands separator
            # and dot is decimal separator (e.g., "1,234.56")
            if cleaned.find(',') < cleaned.find('.'):
                cleaned = cleaned.replace(',', '')
            else:
                # Comma is decimal separator (e.g., "1234,56")
                cleaned = cleaned.replace('.', '').replace(',', '.')
        elif ',' in cleaned:
            # Only comma present - check if it's decimal or thousands separator
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                # Likely decimal separator (e.g., "1234,56")
                cleaned = cleaned.replace(',', '.')
            else:
                # Likely thousands separator (e.g., "1,234")
                cleaned = cleaned.replace(',', '')
        
        try:
            decimal_val = Decimal(cleaned)
            
            # Validate against reasonable bounds for utility payments
            if decimal_val > Decimal('999999999.99'):
                logger.warning(f"Value too large: {value_str} -> {decimal_val}, returning None")
                return None
            
            if decimal_val < Decimal('-999999999.99'):
                logger.warning(f"Value too small: {value_str} -> {decimal_val}, returning None")
                return None
            
            return decimal_val
        except (ValueError, InvalidOperation) as e:
            logger.debug(f"Failed to parse decimal '{value_str}' -> '{cleaned}': {e}")
            return None 
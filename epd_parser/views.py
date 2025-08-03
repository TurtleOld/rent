"""Django views for EPD parser application."""

import logging
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from django.contrib import messages
from django.db import models
from django.db.models import Avg, Count, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
)
from django.views.generic.edit import FormView

from epd_parser.forms import EpdDocumentForm
from epd_parser.models import EpdDocument, ServiceCharge
from epd_parser.pdf_parse import (
    parse_epd_pdf,
    save_epd_document_with_related_data,
)

logger = logging.getLogger(__name__)


class EpdDocumentListView(ListView):
    """View for listing EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/document_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self) -> Any:
        return EpdDocument.objects.prefetch_related("service_charges").order_by(
            "-created_at"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["total_documents"] = EpdDocument.objects.count()
        context["total_amount"] = sum(
            doc.total_with_insurance for doc in context["documents"]
        )
        return cast(dict[str, Any], context)


class EpdDocumentDetailView(DetailView):
    """View for displaying EPD document details."""

    model = EpdDocument
    template_name = "epd_parser/document_detail.html"
    context_object_name = "document"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        document = cast(EpdDocument, self.get_object())
        context["service_charges"] = document.service_charges.all().order_by("order")
        context["meter_readings"] = document.meter_readings.all().order_by("order")
        context["recalculations"] = document.recalculations.all().order_by("order")
        return cast(dict[str, Any], context)


class EpdDocumentCreateView(FormView):
    """View for creating EPD documents with PDF upload and parsing."""

    template_name = "epd_parser/upload.html"
    form_class = EpdDocumentForm
    success_url = None  # Will be set dynamically

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add parsed data to context if available."""
        context = super().get_context_data(**kwargs)
        context["parsed_data"] = self.request.session.get("parsed_data", {})
        return cast(dict[str, Any], context)

    def get_form_kwargs(self) -> dict[str, Any]:
        """Add parsed data to form kwargs."""
        kwargs = super().get_form_kwargs()
        parsed_data = self.request.session.get("parsed_data", {})

        if parsed_data and not kwargs.get("data"):
            # Pre-fill form with parsed data
            kwargs["initial"] = {
                "account_number": parsed_data.get("account_number", ""),
                "full_name": parsed_data.get("full_name", ""),
                "address": parsed_data.get("address", ""),
                "payment_period": parsed_data.get("payment_period", ""),
                "due_date": parsed_data.get("due_date", ""),
                "total_without_insurance": parsed_data.get(
                    "total_without_insurance", Decimal("0.00")
                ),
                "total_with_insurance": parsed_data.get(
                    "total_with_insurance", Decimal("0.00")
                ),
            }

        return cast(dict[str, Any], kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle POST request for both PDF upload and document creation."""
        # Check if this is a document save request (has document form data)
        if "account_number" in request.POST:
            return self.handle_document_save(request)
        else:
            return self.handle_pdf_upload(request)

    def handle_pdf_upload(self, request: HttpRequest) -> HttpResponse:
        """Handle PDF file upload and parsing."""
        if "pdf_file" not in request.FILES:
            messages.error(request, _("Please select a PDF file to upload."))
            return self.render_to_response(self.get_context_data())

        pdf_file = request.FILES["pdf_file"]

        # Validate file
        if not pdf_file.name.lower().endswith(".pdf"):
            messages.error(request, _("Only PDF files are allowed."))
            return self.render_to_response(self.get_context_data())

        if pdf_file.size > 10 * 1024 * 1024:  # 10MB limit
            messages.error(request, _("File size must be less than 10MB."))
            return self.render_to_response(self.get_context_data())

        try:
            # Reset file pointer to beginning
            pdf_file.seek(0)

            # Parse the PDF
            parsed_data = parse_epd_pdf(pdf_file)

            # Check if parsed_data has the expected structure
            if parsed_data and parsed_data.get("account_number"):
                # Store parsed data in session for later use
                session_data = self._prepare_session_data(parsed_data)
                request.session["parsed_data"] = session_data

                messages.success(
                    request,
                    _(
                        "PDF parsed successfully! Found {services_count} services."
                    ).format(services_count=len(parsed_data.get("services", []))),
                )

                return self.render_to_response(self.get_context_data())
            else:
                logger.error("Parsed data is None or missing required fields!")
                messages.error(
                    request, _("Failed to parse PDF data. Please try again.")
                )
                return self.render_to_response(self.get_context_data())

        except Exception as e:
            logger.error(f"Error parsing PDF {pdf_file.name}: {e}")
            messages.error(request, _("Error parsing PDF file. Please try again."))
            return self.render_to_response(self.get_context_data())

    def handle_document_save(self, request: HttpRequest) -> HttpResponse:
        """Handle document form submission and saving."""
        logger.info("Processing document save request")

        # Get parsed data from session
        parsed_data = request.session.get("parsed_data", {})
        if not parsed_data:
            messages.error(request, _("No parsed data found. Please upload PDF again."))
            return redirect("epd_parser:upload")

        # Convert string values back to Decimal for form processing
        parsed_data = self._convert_session_data_back(parsed_data)

        # Create document form with POST data and parsed data
        form = self.get_form()
        # Add parsed_data as dynamic attribute to form
        attr_name = "parsed_data"
        setattr(form, attr_name, parsed_data)

        if form.is_valid():
            try:
                # Save document with all related data
                form_data = form.cleaned_data
                document = save_epd_document_with_related_data(parsed_data, form_data)

                # Clear session data
                if "parsed_data" in request.session:
                    del request.session["parsed_data"]

                messages.success(
                    request,
                    _("Document saved successfully! Account: {account}").format(
                        account=document.account_number
                    ),
                )

                return redirect("epd_parser:document_detail", pk=document.pk)

            except Exception as e:
                logger.error(f"Error saving document: {e}")
                messages.error(
                    request,
                    _("Error saving document: {error}").format(error=str(e)),
                )
        else:
            logger.error(f"Document form errors: {form.errors}")
            messages.error(request, _("Please correct the errors below."))

        # Re-render the form with errors
        return self.render_to_response(self.get_context_data())

    def _prepare_session_data(self, parsed_data: dict[str, Any]) -> dict[str, Any]:
        """Convert parsed data for session storage (Decimal to string)."""
        session_data: dict[str, Any] = {}
        for key, value in parsed_data.items():
            if isinstance(value, Decimal):
                session_data[key] = str(value)
            elif isinstance(value, list):
                # Handle services list
                session_data[key] = []
                for item in value:
                    if isinstance(item, dict):
                        converted_item = {}
                        for item_key, item_value in item.items():
                            if isinstance(item_value, Decimal):
                                converted_item[item_key] = str(item_value)
                            else:
                                converted_item[item_key] = item_value
                        session_data[key].append(converted_item)
                    else:
                        session_data[key].append(item)
            else:
                session_data[key] = value
        return session_data

    def _convert_session_data_back(self, parsed_data: dict[str, Any]) -> dict[str, Any]:
        """Convert session data back to proper types."""
        # Convert string values back to Decimal for form processing
        for key in ["total_without_insurance", "total_with_insurance"]:
            if key in parsed_data and isinstance(parsed_data[key], str):
                parsed_data[key] = Decimal(parsed_data[key])

        # Convert services data back to Decimal
        if "services" in parsed_data:
            for service in parsed_data["services"]:
                for key, value in service.items():
                    if isinstance(value, str) and key in [
                        "volume",
                        "tariff",
                        "amount",
                        "recalculation",
                        "debt",
                        "paid",
                        "total",
                    ]:
                        try:
                            service[key] = Decimal(value)
                        except (ValueError, TypeError):
                            service[key] = None

        return parsed_data


class EpdDocumentUpdateView(FormView):
    """View for updating EPD document data."""

    template_name = "epd_parser/edit.html"
    form_class = EpdDocumentForm
    context_object_name = "document"

    def get_object(self) -> EpdDocument:
        """Get the document to edit."""
        return cast(EpdDocument, get_object_or_404(EpdDocument, pk=self.kwargs["pk"]))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add document to context."""
        context = super().get_context_data(**kwargs)
        context["document"] = self.get_object()
        return cast(dict[str, Any], context)

    def get_initial(self) -> dict[str, Any]:
        """Pre-fill form with current document data."""
        document = self.get_object()
        return {
            "full_name": document.full_name,
            "address": document.address,
            "account_number": document.account_number,
            "payment_period": document.payment_period,
            "due_date": document.due_date,
            "total_without_insurance": document.total_without_insurance,
            "total_with_insurance": document.total_with_insurance,
        }

    def get_success_url(self) -> str:
        """Return URL to redirect to after successful update."""
        document = self.get_object()
        return f"/epd/{document.pk}/"

    def form_valid(self, form: EpdDocumentForm) -> HttpResponse:
        """Handle valid form submission."""
        document = self.get_object()

        # Update document fields manually
        document.full_name = form.cleaned_data["full_name"]
        document.address = form.cleaned_data["address"]
        document.account_number = form.cleaned_data["account_number"]
        document.payment_period = form.cleaned_data["payment_period"]
        document.due_date = form.cleaned_data["due_date"]
        document.total_without_insurance = form.cleaned_data["total_without_insurance"]
        document.total_with_insurance = form.cleaned_data["total_with_insurance"]
        document.save()

        messages.success(self.request, _("EPD document successfully updated!"))
        return redirect("epd_parser:document_detail", pk=document.pk)

    def form_invalid(self, form: EpdDocumentForm) -> HttpResponse:
        """Handle invalid form submission."""
        messages.error(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class EpdDocumentDeleteView(DeleteView):
    """View for deleting EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/document_confirm_delete.html"
    success_url = "/epd/"
    context_object_name = "document"

    def delete(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle document deletion."""
        try:
            response = super().delete(request, *args, **kwargs)
            messages.success(request, _("EPD document successfully deleted!"))
            return response
        except Exception as e:
            document = self.get_object()
            logger.error(f"Error deleting EPD document {document.pk}: {e}")
            messages.error(request, _("An error occurred while deleting the document."))
            return redirect("epd_parser:document_list")


class EpdDocumentSearchView(ListView):
    """View for searching EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/search.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self) -> Any:
        """Filter queryset based on search parameters."""
        queryset = EpdDocument.objects.all()

        query = self.request.GET.get("q", "").strip()
        account_number = self.request.GET.get("account", "").strip()

        if query:
            queryset = queryset.filter(
                models.Q(full_name__icontains=query)
                | models.Q(address__icontains=query)
                | models.Q(payment_period__icontains=query)
            )

        if account_number:
            queryset = queryset.filter(account_number__icontains=account_number)

        return queryset.prefetch_related("service_charges").order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add search parameters to context."""
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        context["account_number"] = self.request.GET.get("account", "").strip()
        return cast(dict[str, Any], context)


class EpdStatisticsView(TemplateView):
    """View for displaying EPD statistics."""

    template_name = "epd_parser/statistics.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add statistics data to context."""
        context = super().get_context_data(**kwargs)

        # Get date range from request
        days = int(self.request.GET.get("days", 30))
        start_date = timezone.now() - timezone.timedelta(days=days)

        # Get statistics
        recent_documents = EpdDocument.objects.filter(created_at__gte=start_date)

        stats = {
            "total_documents": EpdDocument.objects.count(),
            "recent_documents": recent_documents.count(),
            "total_amount": EpdDocument.objects.aggregate(
                total=Sum("total_with_insurance")
            )["total"]
            or Decimal("0.00"),
            "recent_amount": recent_documents.aggregate(
                total=Sum("total_with_insurance")
            )["total"]
            or Decimal("0.00"),
            "avg_amount": EpdDocument.objects.aggregate(
                avg=Avg("total_with_insurance")
            )["avg"]
            or Decimal("0.00"),
            "total_service_charges": ServiceCharge.objects.count(),
            "unique_accounts": EpdDocument.objects.values("account_number")
            .distinct()
            .count(),
        }

        # Get top services
        top_services = (
            ServiceCharge.objects.values("service_name")
            .annotate(count=Count("id"), total_amount=Sum("total"))
            .order_by("-total_amount")[:10]
        )

        context.update(
            {
                "stats": stats,
                "top_services": top_services,
                "days": days,
            }
        )

        return cast(dict[str, Any], context)


class DebugImagesView(TemplateView):
    """View for viewing debug images from PDF processing."""

    template_name = "epd_parser/debug_images.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add debug images data to context."""
        context = super().get_context_data(**kwargs)

        # Get list of debug images
        debug_images: list[dict[str, Any]] = []
        tmp_dir = Path("/tmp")

        # Look for both PNG and JPG debug images
        for img_file in tmp_dir.glob("epd_debug_page_*.png"):
            debug_images.append(
                {
                    "filename": img_file.name,
                    "path": str(img_file),
                    "size": img_file.stat().st_size,
                    "type": "PNG (High Quality)",
                }
            )
        for img_file in tmp_dir.glob("epd_web_debug_page_*.jpg"):
            debug_images.append(
                {
                    "filename": img_file.name,
                    "path": str(img_file),
                    "size": img_file.stat().st_size,
                    "type": "JPG (Web Quality)",
                }
            )

        # Sort by filename
        debug_images.sort(key=lambda x: str(x["filename"]))

        context["debug_images"] = debug_images
        return cast(dict[str, Any], context)


class ParserDemoView(TemplateView):
    """View for parser demo page."""

    template_name = "epd_parser/parser_demo.html"


class ParsePdfApiView(View):
    """API view for parsing PDF files."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Handle PDF parsing API requests."""
        try:
            if "pdf_file" not in request.FILES:
                return JsonResponse(
                    {"success": False, "error": "No PDF file provided"}, status=400
                )

            pdf_file = request.FILES["pdf_file"]

            # Validate file
            if not pdf_file.name.lower().endswith(".pdf"):
                return JsonResponse(
                    {"success": False, "error": "File must be a PDF"}, status=400
                )

            # Save file temporarily and parse
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                for chunk in pdf_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Parse the PDF
                return JsonResponse({"success": True})

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            return JsonResponse({"success": False, "error": str(e)}, status=500)

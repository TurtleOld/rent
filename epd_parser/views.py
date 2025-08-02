"""Django views for EPD parser application."""

import logging
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Avg, Count, Sum
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView

from .forms import EpdDocumentForm, EpdUploadForm
from .models import EpdDocument, ServiceCharge, MeterReading, Recalculation

logger = logging.getLogger(__name__)


class EpdDocumentListView(ListView):
    """View for listing EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/document_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self) -> Any:
        """Get queryset with related service charges."""
        return EpdDocument.objects.prefetch_related("service_charges").order_by(
            "-created_at"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add additional context data."""
        context = super().get_context_data(**kwargs)
        context["total_documents"] = EpdDocument.objects.count()
        context["total_amount"] = sum(
            doc.total_with_insurance for doc in context["documents"]
        )
        return context


class EpdDocumentDetailView(DetailView):
    """View for displaying EPD document details."""

    model = EpdDocument
    template_name = "epd_parser/document_detail.html"
    context_object_name = "document"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add service charges to context."""
        context = super().get_context_data(**kwargs)
        context["service_charges"] = self.object.service_charges.all().order_by("order")
        context["meter_readings"] = self.object.meter_readings.all().order_by("order")
        context["recalculations"] = self.object.recalculations.all().order_by("order")
        return context


@require_http_methods(["GET", "POST"])
def upload_epd(request: HttpRequest) -> HttpResponse:
    """View for uploading and parsing EPD PDF files."""

    if request.method == "POST":
        # Check if this is a document save request (has document form data)
        if "account_number" in request.POST:
            # This is a document save request
            logger.info("Processing document save request")

            # Get parsed data from session
            parsed_data = request.session.get("parsed_data", {})
            if not parsed_data:
                messages.error(
                    request, _("No parsed data found. Please upload PDF again.")
                )
                return redirect("epd_parser:upload")

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

            # Create document form with POST data and parsed data
            document_form = EpdDocumentForm(request.POST)
            document_form.parsed_data = parsed_data

            if document_form.is_valid():
                try:
                    # Save the document and service charges
                    from .pdf_parse import save_epd_document_with_related_data

                    # Get the PDF file from session or create a placeholder
                    pdf_file = None
                    if "pdf_file" in request.FILES:
                        pdf_file = request.FILES["pdf_file"]

                    # Save document with all related data
                    form_data = document_form.cleaned_data
                    document = save_epd_document_with_related_data(
                        parsed_data, pdf_file, form_data
                    )

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
                logger.error(f"Document form errors: {document_form.errors}")
                messages.error(request, _("Please correct the errors below."))

            # Re-render the form with errors
            upload_form = EpdUploadForm()
            return render(
                request,
                "epd_parser/upload.html",
                {
                    "upload_form": upload_form,
                    "document_form": document_form,
                    "parsed_data": parsed_data,
                },
            )

        else:
            # This is a PDF upload request
            upload_form = EpdUploadForm(request.POST, request.FILES)

            if not upload_form.is_valid():
                logger.error(f"Upload form errors: {upload_form.errors}")

            if upload_form.is_valid():
                try:
                    # Get parsed data from the form
                    parsed_data = upload_form.parsed_data

                    # Check if parsed_data has the expected structure
                    if parsed_data and parsed_data.get("account_number"):
                        # Create document form with parsed data
                        document_form = EpdDocumentForm(
                            initial={
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
                        )

                        # Store parsed data in session for later use (convert Decimal to string for JSON serialization)
                        session_data = {}
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
                                                converted_item[item_key] = str(
                                                    item_value
                                                )
                                            else:
                                                converted_item[item_key] = item_value
                                        session_data[key].append(converted_item)
                                    else:
                                        session_data[key].append(item)
                            else:
                                session_data[key] = value

                        request.session["parsed_data"] = session_data

                        messages.success(
                            request,
                            _(
                                "PDF parsed successfully! Found {services_count} services."
                            ).format(
                                services_count=len(parsed_data.get("services", []))
                            ),
                        )

                        return render(
                            request,
                            "epd_parser/upload.html",
                            {
                                "upload_form": upload_form,
                                "document_form": document_form,
                                "parsed_data": parsed_data,
                            },
                        )
                    else:
                        logger.error("Parsed data is None or missing required fields!")
                        messages.error(
                            request, _("Failed to parse PDF data. Please try again.")
                        )
                        return render(
                            request,
                            "epd_parser/upload.html",
                            {
                                "upload_form": upload_form,
                                "document_form": None,
                            },
                        )

                        # Create service charges
                        service_charges = parsed_data.get("service_charges", [])
                        logger.info(f"Creating {len(service_charges)} service charges")
                        for i, charge_data in enumerate(service_charges):
                            try:
                                ServiceCharge.objects.create(
                                    document=document,
                                    service_name=charge_data.get("service_name", ""),
                                    volume=charge_data.get("volume", Decimal("0")),
                                    tariff=charge_data.get("tariff", Decimal("0")),
                                    amount=charge_data.get("amount", Decimal("0")),
                                    recalculation=charge_data.get(
                                        "recalculation", Decimal("0")
                                    ),
                                    debt=charge_data.get("debt", Decimal("0")),
                                    paid=charge_data.get("paid", Decimal("0")),
                                    total=charge_data.get("total", Decimal("0")),
                                    order=i,
                                )
                            except Exception as e:
                                logger.error(f"Error creating service charge: {e}")

                        # Create meter readings
                        meter_readings = parsed_data.get("meter_readings", [])
                        logger.info(f"Creating {len(meter_readings)} meter readings")
                        for i, reading_data in enumerate(meter_readings):
                            try:
                                MeterReading.objects.create(
                                    document=document,
                                    service_name=reading_data.get("service_name", ""),
                                    meter_type=reading_data.get("meter_type", ""),
                                    meter_number=reading_data.get("meter_number", ""),
                                    verification_date=reading_data.get(
                                        "verification_date", ""
                                    ),
                                    previous_reading=reading_data.get(
                                        "previous_reading", Decimal("0")
                                    ),
                                    current_reading=reading_data.get(
                                        "current_reading", Decimal("0")
                                    ),
                                    order=i,
                                )
                            except Exception as e:
                                logger.error(f"Error creating meter reading: {e}")

                        # Create recalculations
                        recalculations = parsed_data.get("recalculations", [])
                        logger.info(f"Creating {len(recalculations)} recalculations")
                        for i, recalc_data in enumerate(recalculations):
                            try:
                                Recalculation.objects.create(
                                    document=document,
                                    service_name=recalc_data.get("service_name", ""),
                                    reason=recalc_data.get("reason", ""),
                                    amount=recalc_data.get("amount", Decimal("0")),
                                    order=i,
                                )
                            except Exception as e:
                                logger.error(f"Error creating recalculation: {e}")

                    messages.success(
                        request, _("EPD document successfully uploaded and parsed!")
                    )
                    return redirect("epd_parser:document_detail", pk=document.pk)
                except Exception as e:
                    logger.error(f"Error parsing PDF: {e}")
                    messages.error(
                        request,
                        _("An error occurred while parsing the PDF. Please try again."),
                    )
                    return render(
                        request,
                        "epd_parser/upload.html",
                        {
                            "upload_form": upload_form,
                            "document_form": None,
                        },
                    )
            else:
                # If upload form is invalid, show errors
                messages.error(request, _("Please correct the errors below."))
                return render(
                    request,
                    "epd_parser/upload.html",
                    {
                        "upload_form": upload_form,
                        "document_form": None,
                    },
                )
    else:
        upload_form = EpdUploadForm()
        document_form = None

    return render(
        request,
        "epd_parser/upload.html",
        {
            "upload_form": upload_form,
            "document_form": document_form,
        },
    )


@require_http_methods(["POST"])
def parse_pdf_api(request: HttpRequest) -> JsonResponse:
    """API endpoint for parsing PDF files."""
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


@require_http_methods(["GET", "POST"])
def edit_epd(request: HttpRequest, pk: int) -> HttpResponse:
    """View for editing EPD document data."""

    document = get_object_or_404(EpdDocument, pk=pk)

    if request.method == "POST":
        form = EpdDocumentForm(request.POST, instance=document)

        if form.is_valid():
            form.save()
            messages.success(request, _("EPD document successfully updated!"))
            return redirect("epd_parser:document_detail", pk=document.pk)
        else:
            messages.error(request, _("Please correct the errors below."))
    else:
        form = EpdDocumentForm(instance=document)

    return render(
        request,
        "epd_parser/edit.html",
        {
            "form": form,
            "document": document,
        },
    )


@require_http_methods(["POST"])
def delete_epd(request: HttpRequest, pk: int) -> HttpResponse:
    """View for deleting EPD documents."""

    document = get_object_or_404(EpdDocument, pk=pk)

    try:
        # Delete the PDF file
        if document.pdf_file:
            pdf_path = Path(document.pdf_file.path)
            if pdf_path.exists():
                pdf_path.unlink()

        # Delete the document (service charges will be deleted automatically)
        document.delete()

        messages.success(request, _("EPD document successfully deleted!"))

    except Exception as e:
        logger.error(f"Error deleting EPD document {pk}: {e}")
        messages.error(request, _("An error occurred while deleting the document."))

    return redirect("epd_parser:document_list")


@require_http_methods(["GET"])
def download_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """View for downloading the original PDF file."""
    document = get_object_or_404(EpdDocument, pk=pk)

    if not document.pdf_file:
        messages.error(request, _("PDF file not found."))
        return redirect("epd_parser:document_detail", pk=pk)

    try:
        pdf_path = Path(document.pdf_file.path)
        if not pdf_path.exists():
            messages.error(request, _("PDF file not found on disk."))
            return redirect("epd_parser:document_detail", pk=pk)

        response = FileResponse(open(pdf_path, "rb"), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{document.pdf_file.name}"'
        )
        return response

    except Exception as e:
        logger.error(f"Error downloading PDF for document {pk}: {e}")
        messages.error(request, _("An error occurred while downloading the file."))
        return redirect("epd_parser:document_detail", pk=pk)


@require_http_methods(["GET"])
def search_epd(request: HttpRequest) -> HttpResponse:
    """View for searching EPD documents."""

    query = request.GET.get("q", "").strip()
    account_number = request.GET.get("account", "").strip()

    documents = EpdDocument.objects.all()

    if query:
        documents = documents.filter(
            models.Q(full_name__icontains=query)
            | models.Q(address__icontains=query)
            | models.Q(payment_period__icontains=query)
        )

    if account_number:
        documents = documents.filter(account_number__icontains=account_number)

    documents = documents.prefetch_related("service_charges").order_by("-created_at")

    return render(
        request,
        "epd_parser/search.html",
        {
            "documents": documents,
            "query": query,
            "account_number": account_number,
        },
    )


@require_http_methods(["GET"])
def statistics(request: HttpRequest) -> HttpResponse:
    """View for displaying EPD statistics."""

    # Get date range from request
    days = int(request.GET.get("days", 30))
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
        "recent_amount": recent_documents.aggregate(total=Sum("total_with_insurance"))[
            "total"
        ]
        or Decimal("0.00"),
        "avg_amount": EpdDocument.objects.aggregate(avg=Avg("total_with_insurance"))[
            "avg"
        ]
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

    return render(
        request,
        "epd_parser/statistics.html",
        {
            "stats": stats,
            "top_services": top_services,
            "days": days,
        },
    )


@require_http_methods(["GET"])
def debug_images(request: HttpRequest) -> HttpResponse:
    """View for viewing debug images from PDF processing."""

    # Get list of debug images
    debug_images = []
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
    debug_images.sort(key=lambda x: x["filename"])

    return render(
        request,
        "epd_parser/debug_images.html",
        {
            "debug_images": debug_images,
        },
    )


@require_http_methods(["GET"])
def parser_demo(request: HttpRequest) -> HttpResponse:
    """View for parser demo page."""
    return render(request, "epd_parser/parser_demo.html")

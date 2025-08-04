"""Django views for EPD parser application."""

import logging
import os
import tempfile
from decimal import Decimal
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

from epd_parser.forms import EpdDocumentForm, PdfUploadForm
from epd_parser.models import (
    EpdDocument,
    ServiceCharge,
)
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
    form_class = PdfUploadForm

    def form_valid(self, form):
        parsed_data = form.parsed_data
        document = save_epd_document_with_related_data(parsed_data)
        return redirect("epd_parser:document_detail", pk=document.pk)

    def form_invalid(self, form):
        logger.error("form_invalid method called")
        logger.error(f"Form is invalid. Errors: {form.errors}")
        error_message = _("Please correct the errors below.")
        messages.error(self.request, error_message)
        return super().form_invalid(form)


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
        return f"/{document.pk}/"

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
    success_url = "/"
    context_object_name = "document"

    def delete(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle document deletion."""
        try:
            response = super().delete(request, *args, **kwargs)
            messages.success(request, _("EPD document successfully deleted!"))
            return response
        except Exception:
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

        # Calculate additional statistics
        total_insurance = EpdDocument.objects.aggregate(total=Sum("insurance_amount"))[
            "total"
        ] or Decimal("0.00")

        total_debt = ServiceCharge.objects.aggregate(total=Sum("debt"))[
            "total"
        ] or Decimal("0.00")

        total_paid = ServiceCharge.objects.aggregate(total=Sum("paid"))[
            "total"
        ] or Decimal("0.00")

        # Calculate growth rate (comparing recent period with previous period)
        previous_start_date = start_date - timezone.timedelta(days=days)
        previous_documents = EpdDocument.objects.filter(
            created_at__gte=previous_start_date, created_at__lt=start_date
        ).count()

        growth_rate = 0
        if previous_documents > 0:
            growth_rate = (
                (recent_documents.count() - previous_documents) / previous_documents
            ) * 100

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
            "avg_service_amount": ServiceCharge.objects.aggregate(avg=Avg("total"))[
                "avg"
            ]
            or Decimal("0.00"),
            "unique_accounts": EpdDocument.objects.values("account_number")
            .distinct()
            .count(),
            "total_insurance": total_insurance,
            "total_debt": total_debt,
            "total_paid": total_paid,
            "growth_rate": growth_rate,
        }

        # Get top services
        top_services = (
            ServiceCharge.objects.values("service_name")
            .annotate(count=Count("id"), total_amount=Sum("total"))
            .order_by("-total_amount")[:10]
        )

        # Calculate total amount for percentage calculation
        total_service_amount = sum(service["total_amount"] for service in top_services)

        # Calculate average amount and percentage for each service
        for service in top_services:
            if service["count"] > 0:
                service["avg_amount"] = service["total_amount"] / service["count"]
            else:
                service["avg_amount"] = Decimal("0.00")

            # Calculate percentage of total
            if total_service_amount > 0:
                service["percentage"] = (
                    service["total_amount"] / total_service_amount
                ) * 100
            else:
                service["percentage"] = Decimal("0.00")

        context.update(
            {
                "stats": stats,
                "top_services": top_services,
                "days": days,
            }
        )

        return cast(dict[str, Any], context)


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
                parsed_data = parse_epd_pdf(pdf_file)

                return JsonResponse({"success": True, "data": parsed_data})

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception:
            return JsonResponse(
                {"success": False, "error": "Internal error"}, status=500
            )


class StatisticsApiView(View):
    """API view for exporting statistics data."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Return statistics data in JSON format."""
        try:
            # Get date range from request
            days = int(request.GET.get("days", 30))
            start_date = timezone.now() - timezone.timedelta(days=days)

            # Get statistics (reuse logic from EpdStatisticsView)
            recent_documents = EpdDocument.objects.filter(created_at__gte=start_date)

            # Calculate additional statistics
            total_insurance = EpdDocument.objects.aggregate(
                total=Sum("insurance_amount")
            )["total"] or Decimal("0.00")

            total_debt = ServiceCharge.objects.aggregate(total=Sum("debt"))[
                "total"
            ] or Decimal("0.00")

            total_paid = ServiceCharge.objects.aggregate(total=Sum("paid"))[
                "total"
            ] or Decimal("0.00")

            # Calculate growth rate
            previous_start_date = start_date - timezone.timedelta(days=days)
            previous_documents = EpdDocument.objects.filter(
                created_at__gte=previous_start_date, created_at__lt=start_date
            ).count()

            growth_rate = 0
            if previous_documents > 0:
                growth_rate = (
                    (recent_documents.count() - previous_documents) / previous_documents
                ) * 100

            stats = {
                "total_documents": EpdDocument.objects.count(),
                "recent_documents": recent_documents.count(),
                "total_amount": float(
                    EpdDocument.objects.aggregate(total=Sum("total_with_insurance"))[
                        "total"
                    ]
                    or Decimal("0.00")
                ),
                "recent_amount": float(
                    recent_documents.aggregate(total=Sum("total_with_insurance"))[
                        "total"
                    ]
                    or Decimal("0.00")
                ),
                "avg_amount": float(
                    EpdDocument.objects.aggregate(avg=Avg("total_with_insurance"))[
                        "avg"
                    ]
                    or Decimal("0.00")
                ),
                "total_service_charges": ServiceCharge.objects.count(),
                "avg_service_amount": float(
                    ServiceCharge.objects.aggregate(avg=Avg("total"))["avg"]
                    or Decimal("0.00")
                ),
                "unique_accounts": EpdDocument.objects.values("account_number")
                .distinct()
                .count(),
                "total_insurance": float(total_insurance),
                "total_debt": float(total_debt),
                "total_paid": float(total_paid),
                "growth_rate": float(growth_rate),
                "period_days": days,
            }

            # Get top services
            top_services = (
                ServiceCharge.objects.values("service_name")
                .annotate(count=Count("id"), total_amount=Sum("total"))
                .order_by("-total_amount")[:10]
            )

            # Calculate total amount for percentage calculation
            total_service_amount = sum(
                service["total_amount"] for service in top_services
            )

            # Calculate average amount and percentage for each service
            services_data = []
            for service in top_services:
                if service["count"] > 0:
                    avg_amount = service["total_amount"] / service["count"]
                else:
                    avg_amount = Decimal("0.00")

                # Calculate percentage of total
                if total_service_amount > 0:
                    percentage = (service["total_amount"] / total_service_amount) * 100
                else:
                    percentage = Decimal("0.00")

                services_data.append(
                    {
                        "service_name": service["service_name"],
                        "count": service["count"],
                        "total_amount": float(service["total_amount"]),
                        "avg_amount": float(avg_amount),
                        "percentage": float(percentage),
                    }
                )

            return JsonResponse(
                {
                    "success": True,
                    "data": {
                        "statistics": stats,
                        "top_services": services_data,
                        "generated_at": timezone.now().isoformat(),
                    },
                }
            )

        except Exception:
            return JsonResponse(
                {"success": False, "error": "Failed to generate statistics"}, status=500
            )




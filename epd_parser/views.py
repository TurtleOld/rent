"""Django views for EPD parser application."""

import logging
import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.db.models import Avg, Count, Max, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, TemplateView
from django.views.generic.edit import FormView

from epd_parser.forms import EpdDocumentForm, PdfUploadForm
from epd_parser.models import EpdDocument, ServiceCharge
from epd_parser.pdf_parse import parse_epd_pdf, save_epd_document_with_related_data

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    """View for the home page.

    Shows different content for authenticated and anonymous users.
    """

    template_name = "epd_parser/home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for the home page.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with statistics for authenticated users.
        """
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            context["total_documents"] = EpdDocument.objects.count()
            context["total_amount"] = EpdDocument.objects.aggregate(
                total=Sum("total_with_insurance")
            )["total"] or Decimal("0.00")
            context["recent_documents"] = EpdDocument.objects.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count()
            context["unique_accounts"] = (
                EpdDocument.objects.values("account_number").distinct().count()
            )
        else:
            context["is_anonymous"] = True

        return context


class EpdDocumentListView(LoginRequiredMixin, ListView):
    """View for listing EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/document_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self) -> Any:
        """Get queryset for EPD documents.

        Returns:
            Any: Queryset with prefetched service charges, ordered by creation date.
        """
        return EpdDocument.objects.prefetch_related("service_charges").order_by(
            "-created_at"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for the document list.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with document statistics.
        """
        context = super().get_context_data(**kwargs)

        stats = EpdDocument.objects.aggregate(
            total_documents=Count("id"), total_amount=Sum("total_with_insurance")
        )

        context["total_documents"] = stats["total_documents"] or 0
        context["total_amount"] = stats["total_amount"] or Decimal("0.00")
        return context


class EpdDocumentDetailView(LoginRequiredMixin, DetailView):
    """View for displaying EPD document details."""

    model = EpdDocument
    template_name = "epd_parser/document_detail.html"
    context_object_name = "document"

    def get_queryset(self) -> Any:
        """Get queryset for EPD document details.

        Returns:
            Any: Queryset with prefetched related objects.
        """
        return EpdDocument.objects.prefetch_related(
            "service_charges", "meter_readings", "recalculations"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for document details.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with ordered related objects.
        """
        context = super().get_context_data(**kwargs)
        document = self.get_object()
        context["service_charges"] = document.service_charges.all().order_by("order")
        context["meter_readings"] = document.meter_readings.all().order_by("order")
        context["recalculations"] = document.recalculations.all().order_by("order")
        return context


class EpdDocumentCreateView(LoginRequiredMixin, FormView):
    """View for creating EPD documents with PDF upload and parsing."""

    template_name = "epd_parser/upload.html"
    form_class = PdfUploadForm

    def form_valid(self, form: PdfUploadForm) -> HttpResponse:
        """Handle valid form submission.

        Args:
            form: The validated PDF upload form.

        Returns:
            HttpResponse: Redirect to document detail page.
        """
        parsed_data = form.parsed_data
        document = save_epd_document_with_related_data(parsed_data)
        return redirect("epd_parser:document_detail", pk=document.pk)

    def form_invalid(self, form: PdfUploadForm) -> HttpResponse:
        """Handle invalid form submission.

        Args:
            form: The invalid PDF upload form.

        Returns:
            HttpResponse: Render form with errors.
        """
        logger.error("form_invalid method called")
        logger.error(f"Form is invalid. Errors: {form.errors}")
        error_message = _("Please correct the errors below.")
        messages.error(self.request, error_message)
        return super().form_invalid(form)


class EpdDocumentUpdateView(LoginRequiredMixin, FormView):
    """View for updating EPD document data."""

    template_name = "epd_parser/edit.html"
    form_class = EpdDocumentForm
    context_object_name = "document"

    def get_object(self) -> EpdDocument:
        """Get the document to edit.

        Returns:
            EpdDocument: The document to be edited.
        """
        return get_object_or_404(EpdDocument, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add document to context.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with document.
        """
        context = super().get_context_data(**kwargs)
        context["document"] = self.get_object()
        return context

    def get_initial(self) -> dict[str, Any]:
        """Pre-fill form with current document data.

        Returns:
            dict[str, Any]: Initial form data from document.
        """
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
        """Return URL to redirect to after successful update.

        Returns:
            str: URL to document detail page.
        """
        document = self.get_object()
        return f"/{document.pk}/"

    def form_valid(self, form: EpdDocumentForm) -> HttpResponse:
        """Handle valid form submission.

        Args:
            form: The validated document form.

        Returns:
            HttpResponse: Redirect to document detail page.
        """
        document = self.get_object()

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
        """Handle invalid form submission.

        Args:
            form: The invalid document form.

        Returns:
            HttpResponse: Render form with errors.
        """
        messages.error(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class EpdDocumentDeleteView(LoginRequiredMixin, DeleteView):
    """View for deleting EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/document_confirm_delete.html"
    success_url = "/"
    context_object_name = "document"

    def delete(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle document deletion.

        Args:
            request: The HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            HttpResponse: Redirect response after deletion.
        """
        try:
            response = super().delete(request, *args, **kwargs)
            messages.success(request, _("EPD document successfully deleted!"))
            return response
        except Exception:
            messages.error(request, _("An error occurred while deleting the document."))
            return redirect("epd_parser:document_list")


class EpdDocumentSearchView(LoginRequiredMixin, ListView):
    """View for searching EPD documents."""

    model = EpdDocument
    template_name = "epd_parser/search.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self) -> Any:
        """Filter queryset based on search parameters.

        Returns:
            Any: Filtered queryset based on search criteria.
        """
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
        """Add search parameters to context.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with search parameters.
        """
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        context["account_number"] = self.request.GET.get("account", "").strip()
        return context


class EpdStatisticsView(LoginRequiredMixin, TemplateView):
    """View for displaying EPD statistics."""

    template_name = "epd_parser/statistics.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add statistics data to context.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict[str, Any]: Context data with comprehensive statistics.
        """
        context = super().get_context_data(**kwargs)

        days = int(self.request.GET.get("days", 30))
        start_date = timezone.now() - timedelta(days=days)
        previous_start_date = start_date - timedelta(days=days)

        recent_documents = EpdDocument.objects.filter(created_at__gte=start_date)

        main_stats = EpdDocument.objects.aggregate(
            total_documents=Count("id"),
            total_amount=Sum("total_without_insurance"),
            avg_amount=Avg("total_without_insurance"),
            total_insurance=Sum("insurance_amount"),
            unique_accounts=Count("account_number", distinct=True),
        )

        recent_stats = recent_documents.aggregate(
            recent_documents=Count("id"), recent_amount=Sum("total_without_insurance")
        )

        service_stats = ServiceCharge.objects.aggregate(
            total_debt=Sum("debt"),
            total_paid=Sum("paid"),
            avg_service_amount=Avg("total"),
            unique_services=Count("service_name", distinct=True),
        )
        previous_documents = EpdDocument.objects.filter(
            created_at__gte=previous_start_date, created_at__lt=start_date
        ).count()

        growth_rate = 0
        if previous_documents > 0:
            growth_rate = (
                (recent_stats["recent_documents"] - previous_documents)
                / previous_documents
            ) * 100

        stats = {
            "total_documents": main_stats["total_documents"] or 0,
            "recent_documents": recent_stats["recent_documents"] or 0,
            "total_amount": main_stats["total_amount"] or Decimal("0.00"),
            "recent_amount": recent_stats["recent_amount"] or Decimal("0.00"),
            "avg_amount": main_stats["avg_amount"] or Decimal("0.00"),
            "total_service_charges": service_stats["unique_services"] or 0,
            "avg_service_amount": service_stats["avg_service_amount"]
            or Decimal("0.00"),
            "unique_accounts": main_stats["unique_accounts"] or 0,
            "total_insurance": main_stats["total_insurance"] or Decimal("0.00"),
            "total_debt": service_stats["total_debt"] or Decimal("0.00"),
            "total_paid": service_stats["total_paid"] or Decimal("0.00"),
            "growth_rate": growth_rate,
        }

        top_services = list(
            ServiceCharge.objects.values("service_name")
            .annotate(
                count=Count("document", distinct=True),
                total_amount=Sum("total"),
            )
            .order_by("-total_amount")[:10]
        )

        total_service_amount = sum(service["total_amount"] for service in top_services)

        for service in top_services:
            if service["count"] > 0:
                service["avg_amount"] = service["total_amount"] / service["count"]
            else:
                service["avg_amount"] = Decimal("0.00")

            if total_service_amount > 0:
                service["percentage"] = (
                    service["total_amount"] / total_service_amount
                ) * 100
            else:
                service["percentage"] = Decimal("0.00")

        services_by_accounts = list(
            ServiceCharge.objects.values("service_name")
            .annotate(
                accounts_count=Count("document__account_number", distinct=True),
                total_amount=Sum("total"),
            )
            .order_by("-total_amount")[:10]
        )

        total_accounts_amount = sum(
            service["total_amount"] for service in services_by_accounts
        )
        for service in services_by_accounts:
            if total_accounts_amount > 0:
                service["percentage"] = (
                    service["total_amount"] / total_accounts_amount
                ) * 100
            else:
                service["percentage"] = Decimal("0.00")

        timeline_data = self._get_timeline_data(days)
        account_charts_data = self._get_account_charts_data()

        accounts_data = self._get_accounts_data()
        accounts_stats = self._get_accounts_statistics()

        context.update(
            {
                "stats": stats,
                "top_services": top_services,
                "services_by_accounts": services_by_accounts,
                "timeline_data": timeline_data,
                "account_charts_data": account_charts_data,
                "accounts_data": accounts_data,
                "accounts_stats": accounts_stats,
                "days": days,
            }
        )

        return context

    def _get_timeline_data(self, days: int) -> dict[str, Any]:
        """Get timeline data for charts.

        Args:
            days: Number of days to include in timeline.

        Returns:
            dict[str, Any]: Timeline data with dates, counts, and amounts.
        """
        from django.db.models.functions import TruncDate

        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        daily_counts = (
            EpdDocument.objects.filter(created_at__gte=start_date)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        daily_amounts = (
            EpdDocument.objects.filter(created_at__gte=start_date)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total=Sum("total_with_insurance"))
            .order_by("date")
        )

        dates = []
        counts = []
        amounts = []

        current_date = start_date.date()
        while current_date <= end_date.date():
            dates.append(current_date.strftime("%d.%m"))

            count_data = next(
                (item for item in daily_counts if item["date"] == current_date), None
            )
            counts.append(count_data["count"] if count_data else 0)

            amount_data = next(
                (item for item in daily_amounts if item["date"] == current_date), None
            )
            amounts.append(float(amount_data["total"]) if amount_data else 0.0)

            current_date += timedelta(days=1)

        return {"dates": dates, "counts": counts, "amounts": amounts}

    def _get_account_charts_data(self) -> list[dict[str, Any]]:
        """Get data for individual account charts.

        Returns:
            list[dict[str, Any]]: Account charts data with services and percentages.
        """
        account_services_data = (
            ServiceCharge.objects.select_related("document")
            .values("document__account_number", "document__full_name", "service_name")
            .annotate(total_amount=Sum("total"), count=Count("id"))
            .order_by("document__account_number", "-total_amount")
        )
        accounts_dict = {}
        for item in account_services_data:
            account_number = item["document__account_number"]
            full_name = item["document__full_name"]

            if account_number not in accounts_dict:
                accounts_dict[account_number] = {
                    "account_number": account_number,
                    "full_name": full_name,
                    "services": [],
                    "total_amount": Decimal("0.00"),
                }

            service_data = {
                "service_name": item["service_name"],
                "total_amount": item["total_amount"],
                "count": item["count"],
            }
            accounts_dict[account_number]["services"].append(service_data)
            accounts_dict[account_number]["total_amount"] += item["total_amount"]

        account_charts = []
        for account_data in accounts_dict.values():
            total_amount = account_data["total_amount"]
            for service in account_data["services"]:
                if total_amount > 0:
                    service["percentage"] = (
                        service["total_amount"] / total_amount
                    ) * 100
                else:
                    service["percentage"] = Decimal("0.00")

            if account_data["services"]:
                account_charts.append(account_data)

        return account_charts

    def _get_accounts_data(self) -> list[dict[str, Any]]:
        """Get accounts data for dropdown and individual account statistics.

        Returns:
            list[dict[str, Any]]: Accounts data with statistics and top services.
        """
        accounts_data = (
            EpdDocument.objects.values("account_number", "full_name")
            .annotate(
                total_amount=Sum("total_without_insurance", distinct=True),
                services_count=Count("service_charges", distinct=True),
                documents_count=Count("id", distinct=True),
            )
            .order_by("-total_amount")
        )

        accounts_list = []
        for account in accounts_data:
            account_number = account["account_number"]

            top_services = (
                ServiceCharge.objects.filter(document__account_number=account_number)
                .values("service_name")
                .annotate(amount=Sum("total"))
                .order_by("-amount")[:5]
            )

            account_data = {
                "account_number": account_number,
                "full_name": account["full_name"],
                "total_amount": float(account["total_amount"]),
                "services_count": account["services_count"],
                "documents_count": account["documents_count"],
                "top_services": [
                    {
                        "service_name": service["service_name"],
                        "amount": float(service["amount"]),
                    }
                    for service in top_services
                ],
            }
            accounts_list.append(account_data)

        return accounts_list

    def _get_accounts_statistics(self) -> dict[str, Any]:
        """Get statistics for accounts section.

        Returns:
            dict[str, Any]: Account statistics including totals and averages.
        """
        unique_accounts = EpdDocument.objects.values("account_number").distinct()
        total_accounts = unique_accounts.count()

        accounts_data = (
            EpdDocument.objects.values("account_number")
            .annotate(account_total=Sum("total_without_insurance"))
            .aggregate(
                total_amount=Sum("account_total"),
                top_amount=Max("account_total"),
            )
        )

        total_services = ServiceCharge.objects.count()
        avg_services = total_services / total_accounts if total_accounts > 0 else 0

        return {
            "total_accounts": total_accounts,
            "total_amount": float(accounts_data["total_amount"] or Decimal("0.00")),
            "avg_services": float(avg_services),
            "top_amount": float(accounts_data["top_amount"] or Decimal("0.00")),
        }


class ParsePdfApiView(LoginRequiredMixin, View):
    """API view for parsing PDF files."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Handle PDF parsing API requests.

        Args:
            request: The HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            JsonResponse: Response with parsed data or error message.
        """
        try:
            if "pdf_file" not in request.FILES:
                return JsonResponse(
                    {"success": False, "error": "No PDF file provided"}, status=400
                )

            pdf_file = request.FILES["pdf_file"]

            if not pdf_file.name.lower().endswith(".pdf"):
                return JsonResponse(
                    {"success": False, "error": "File must be a PDF"}, status=400
                )

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                for chunk in pdf_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                parsed_data = parse_epd_pdf(pdf_file)

                return JsonResponse({"success": True, "data": parsed_data})

            finally:
                os.unlink(temp_file_path)

        except Exception:
            return JsonResponse(
                {"success": False, "error": "Internal error"}, status=500
            )


class StatisticsApiView(LoginRequiredMixin, View):
    """API view for exporting statistics data."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Return statistics data in JSON format.

        Args:
            request: The HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            JsonResponse: Response with statistics data or error message.
        """
        try:
            days = int(request.GET.get("days", 30))
            start_date = timezone.now() - timedelta(days=days)
            previous_start_date = start_date - timedelta(days=days)

            recent_documents = EpdDocument.objects.filter(created_at__gte=start_date)

            accounts_totals = (
                EpdDocument.objects.values("account_number")
                .annotate(account_total=Sum("total_without_insurance"))
                .aggregate(
                    total_amount=Sum("account_total"),
                    avg_amount=Avg("account_total"),
                )
            )

            main_stats = EpdDocument.objects.aggregate(
                total_documents=Count("id"),
                total_insurance=Sum("insurance_amount"),
                unique_accounts=Count("account_number", distinct=True),
            )

            main_stats.update(accounts_totals)

            recent_stats = recent_documents.aggregate(
                recent_documents=Count("id"),
                recent_amount=Sum("total_without_insurance"),
            )

            service_stats = ServiceCharge.objects.aggregate(
                total_debt=Sum("debt"),
                total_paid=Sum("paid"),
                avg_service_amount=Avg("total"),
                total_service_charges=Count("id"),
            )
            previous_documents = EpdDocument.objects.filter(
                created_at__gte=previous_start_date, created_at__lt=start_date
            ).count()

            growth_rate = 0
            if previous_documents > 0:
                growth_rate = (
                    (recent_stats["recent_documents"] - previous_documents)
                    / previous_documents
                ) * 100

            stats = {
                "total_documents": main_stats["total_documents"] or 0,
                "recent_documents": recent_stats["recent_documents"] or 0,
                "total_amount": float(main_stats["total_amount"] or Decimal("0.00")),
                "recent_amount": float(
                    recent_stats["recent_amount"] or Decimal("0.00")
                ),
                "avg_amount": float(main_stats["avg_amount"] or Decimal("0.00")),
                "total_service_charges": service_stats["total_service_charges"] or 0,
                "avg_service_amount": float(
                    service_stats["avg_service_amount"] or Decimal("0.00")
                ),
                "unique_accounts": main_stats["unique_accounts"] or 0,
                "total_insurance": float(
                    main_stats["total_insurance"] or Decimal("0.00")
                ),
                "total_debt": float(service_stats["total_debt"] or Decimal("0.00")),
                "total_paid": float(service_stats["total_paid"] or Decimal("0.00")),
                "growth_rate": float(growth_rate),
                "period_days": days,
            }

            top_services = (
                ServiceCharge.objects.values("service_name")
                .annotate(count=Count("id"), total_amount=Sum("total"))
                .order_by("-total_amount")[:10]
            )

            total_service_amount = sum(
                service["total_amount"] for service in top_services
            )

            services_data = []
            for service in top_services:
                if service["count"] > 0:
                    avg_amount = service["total_amount"] / service["count"]
                else:
                    avg_amount = Decimal("0.00")

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

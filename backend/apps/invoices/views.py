from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, permissions, status, views
from rest_framework.response import Response

from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer

from .models import Invoice, LineItem, Service
from .serializers import InvoiceSerializer, InvoiceUploadSerializer, ServiceSerializer
from .tasks import process_invoice


def _invoice_queryset(user):
    return (
        Invoice.objects.filter(user=user)
        .prefetch_related("line_items")
        .annotate(
            _total_paid=Coalesce(
                Sum("payments__amount"),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("-created_at")
    )


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return _invoice_queryset(self.request.user)


class InvoiceUploadView(generics.CreateAPIView):
    serializer_class = InvoiceUploadSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        invoice = serializer.instance
        # Trigger async processing after save
        process_invoice.delay(invoice.pk)
        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )


class InvoiceDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return _invoice_queryset(self.request.user)


class InvoiceFileDownloadView(views.APIView):
    """Serves an invoice PDF via X-Accel-Redirect (nginx internal redirect).

    Only the authenticated owner of the invoice can download it.
    The response body is empty; nginx replaces it with the actual file.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        response = HttpResponse(status=200, content_type="application/pdf")
        response["X-Accel-Redirect"] = f"/protected-media/{invoice.pdf_file.name}"
        response["Content-Disposition"] = f'inline; filename="invoice_{pk}.pdf"'
        return response


class ServiceListView(generics.ListAPIView):
    """Returns all services belonging to the authenticated user."""

    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Service.objects.filter(user=self.request.user)
            .prefetch_related("aliases")
            .order_by("canonical_name")
        )


class ServiceTariffHistoryView(views.APIView):
    """Returns tariff history for a single service across all processed invoices.

    Each point in the history represents one invoice period where this service
    appeared. Points are ordered by period (year, month). Change percentage
    is relative to the immediately preceding point.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int) -> Response:
        service = get_object_or_404(Service, pk=pk, user=request.user)
        qs = (
            LineItem.objects
            .filter(service=service, invoice__status="processed")
            .select_related("invoice")
            .order_by("invoice__period_year", "invoice__period_month")
            .values(
                "invoice__period_year",
                "invoice__period_month",
                "tariff",
                "invoice__id",
            )
        )
        points = []
        prev_tariff = None
        for row in qs:
            tariff = row["tariff"]
            change_pct = None
            if tariff is not None and prev_tariff is not None and prev_tariff != 0:
                change_pct = round(
                    float((tariff - prev_tariff) / prev_tariff * 100), 2
                )
            points.append(
                {
                    "invoice_id": row["invoice__id"],
                    "year": row["invoice__period_year"],
                    "month": row["invoice__period_month"],
                    "tariff": tariff,
                    "change_pct": change_pct,
                }
            )
            if tariff is not None:
                prev_tariff = tariff
        return Response({"service": ServiceSerializer(service).data, "points": points})


class InvoiceReparseView(views.APIView):
    """Resets invoice status to PROCESSING and re-queues the parsing task.

    Only available when invoice is in 'processed' or 'failed' state.
    Clears error_message and warnings; line_items are rebuilt by the task.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int) -> Response:
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        if invoice.status == Invoice.Status.PROCESSING:
            return Response(
                {"detail": "Инвойс уже обрабатывается."},
                status=status.HTTP_409_CONFLICT,
            )
        invoice.status = Invoice.Status.PROCESSING
        invoice.error_message = None
        invoice.warnings = []
        invoice.save(update_fields=["status", "error_message", "warnings", "updated_at"])
        process_invoice.delay(invoice.pk)
        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_202_ACCEPTED,
        )


class InvoicePaymentListCreateView(generics.ListCreateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_invoice(self) -> Invoice:
        return get_object_or_404(Invoice, pk=self.kwargs["pk"], user=self.request.user)

    def get_queryset(self):
        return Payment.objects.filter(invoice=self._get_invoice())

    def perform_create(self, serializer):
        serializer.save(invoice=self._get_invoice(), user=self.request.user)

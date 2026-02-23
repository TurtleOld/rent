from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, permissions, status
from rest_framework.response import Response

from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer

from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceUploadSerializer
from .tasks import process_invoice


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Invoice.objects.filter(user=self.request.user)
            .prefetch_related("line_items", "payments")
        )


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


class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return (
            Invoice.objects.filter(user=self.request.user)
            .prefetch_related("line_items", "payments")
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

from django.urls import path

from .views import (
    InvoiceDetailView,
    InvoiceFileDownloadView,
    InvoiceListView,
    InvoicePaymentListCreateView,
    InvoiceReparseView,
    InvoiceUploadView,
)

urlpatterns = [
    path("", InvoiceListView.as_view(), name="invoice-list"),
    path("upload/", InvoiceUploadView.as_view(), name="invoice-upload"),
    path("<int:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path("<int:pk>/file/", InvoiceFileDownloadView.as_view(), name="invoice-file"),
    path("<int:pk>/reparse/", InvoiceReparseView.as_view(), name="invoice-reparse"),
    path("<int:pk>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
]

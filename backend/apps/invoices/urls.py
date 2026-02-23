from django.urls import path

from .views import (
    InvoiceDetailView,
    InvoiceListView,
    InvoicePaymentListCreateView,
    InvoiceUploadView,
)

urlpatterns = [
    path("", InvoiceListView.as_view(), name="invoice-list"),
    path("upload/", InvoiceUploadView.as_view(), name="invoice-upload"),
    path("<int:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path("<int:pk>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
]

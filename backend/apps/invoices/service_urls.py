from django.urls import path

from .views import ServiceListView, ServiceTariffHistoryView

urlpatterns = [
    path("", ServiceListView.as_view(), name="service-list"),
    path("<int:pk>/history/", ServiceTariffHistoryView.as_view(), name="service-tariff-history"),
]

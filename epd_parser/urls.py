"""URL configuration for EPD parser application."""

from django.urls import path

from . import views

app_name = "epd_parser"

urlpatterns = [
    # Document management
    path("", views.EpdDocumentListView.as_view(), name="document_list"),
    path("upload/", views.EpdDocumentCreateView.as_view(), name="upload"),
    path("<int:pk>/", views.EpdDocumentDetailView.as_view(), name="document_detail"),
    path("<int:pk>/edit/", views.EpdDocumentUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.EpdDocumentDeleteView.as_view(), name="delete"),
    # Search and statistics
    path("search/", views.EpdDocumentSearchView.as_view(), name="search"),
    path("statistics/", views.EpdStatisticsView.as_view(), name="statistics"),
    # API endpoints
    path("api/parse-pdf/", views.ParsePdfApiView.as_view(), name="parse_pdf_api"),
    path("api/statistics/", views.StatisticsApiView.as_view(), name="statistics_api"),
]

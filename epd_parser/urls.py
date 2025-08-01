"""URL configuration for EPD parser application."""

from django.urls import path

from . import views

app_name = 'epd_parser'

urlpatterns = [
    # Document management
    path('', views.EpdDocumentListView.as_view(), name='document_list'),
    path('upload/', views.upload_epd, name='upload'),
    path('<int:pk>/', views.EpdDocumentDetailView.as_view(), name='document_detail'),
    path('<int:pk>/edit/', views.edit_epd, name='edit'),
    path('<int:pk>/delete/', views.delete_epd, name='delete'),
    path('<int:pk>/download/', views.download_pdf, name='download_pdf'),
    
    # Search and statistics
    path('search/', views.search_epd, name='search'),
    path('statistics/', views.statistics, name='statistics'),
] 
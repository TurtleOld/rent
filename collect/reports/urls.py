from django.urls import path

from collect.reports.views import ReportsView

app_name = 'reports'
urlpatterns = [
    path('', ReportsView.as_view(), name='list'),
]

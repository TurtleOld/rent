from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/invoices/", include("apps.invoices.urls")),
    path("api/services/", include("apps.invoices.service_urls")),
]

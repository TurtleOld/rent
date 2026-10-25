from django.contrib.admin.apps import AdminConfig


class RentAdminConfig(AdminConfig):
    default_site = "apps.accounts.admin_site.RateLimitedAdminSite"

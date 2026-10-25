from django.contrib.admin import AdminSite
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit


@method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True), name="login")
class RateLimitedAdminSite(AdminSite):
    """Админка с ограничением попыток входа по реальному IP клиента.

    Лимит совпадает с лимитом входа в API, а IP берётся через общий
    RATELIMIT_IP_META_KEY, поэтому за nginx учитывается X-Real-IP.
    Ограничиваются только POST-запросы страницы входа: обычная работа
    в админке после входа не блокируется.
    """

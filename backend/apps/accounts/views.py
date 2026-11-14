from django.utils.decorators import method_decorator
from django_ratelimit.core import get_usage
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions
from rest_framework.exceptions import Throttled
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer

LOGIN_RATE_LIMIT = "5/m"
LOGIN_RATE_LIMIT_GROUP = "login"
_LOGIN_RATE_LIMIT_SECONDS = 60


def _login_retry_after(request) -> int:
    """Возвращает время до конца текущего окна лимита входа.

    Args:
        request: Запрос, для которого уже сработал лимит.

    Returns:
        Целое число секунд от 1 до 60.
    """
    usage = get_usage(
        request,
        group=LOGIN_RATE_LIMIT_GROUP,
        key="ip",
        rate=LOGIN_RATE_LIMIT,
        increment=False,
    )
    if usage is None or usage["time_left"] < 1:
        return _LOGIN_RATE_LIMIT_SECONDS
    return min(usage["time_left"], _LOGIN_RATE_LIMIT_SECONDS)


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]

    # block=True отдал бы 403 (Ratelimited — это PermissionDenied), а фронтенд ждёт 429.
    @method_decorator(
        ratelimit(
            group=LOGIN_RATE_LIMIT_GROUP,
            key="ip",
            rate=LOGIN_RATE_LIMIT,
            block=False,
        )
    )
    def post(self, request, *args, **kwargs):
        if request.limited:
            # wait передаётся после создания: конструктор Throttled дописывает
            # к detail английское «Expected available in…», а текст ошибки менять нельзя.
            exc = Throttled(detail="Слишком много попыток входа. Попробуйте позже.")
            exc.wait = _login_retry_after(request)
            raise exc
        return super().post(request, *args, **kwargs)


class LogoutView(TokenBlacklistView):
    """Blacklists the provided refresh token, invalidating the session."""

    permission_classes = [permissions.AllowAny]

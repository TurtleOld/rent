from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions
from rest_framework.exceptions import Throttled
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]

    # block=True отдал бы 403 (Ratelimited — это PermissionDenied), а фронтенд ждёт 429.
    @method_decorator(ratelimit(key="ip", rate="5/m", block=False))
    def post(self, request, *args, **kwargs):
        if request.limited:
            raise Throttled(detail="Слишком много попыток входа. Попробуйте позже.")
        return super().post(request, *args, **kwargs)


class LogoutView(TokenBlacklistView):
    """Blacklists the provided refresh token, invalidating the session."""

    permission_classes = [permissions.AllowAny]

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer


@method_decorator(ratelimit(key="ip", rate="3/h", block=True), name="post")
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


@method_decorator(ratelimit(key="ip", rate="5/m", block=True), name="post")
class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class LogoutView(TokenBlacklistView):
    """Blacklists the provided refresh token, invalidating the session."""

    permission_classes = [permissions.AllowAny]

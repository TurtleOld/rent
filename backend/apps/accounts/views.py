from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class LogoutView(TokenBlacklistView):
    """Blacklists the provided refresh token, invalidating the session."""

    permission_classes = [permissions.AllowAny]

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class UserRegistrationTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_user_registration(self):
        response = self.client.post(
            "/api/auth/register/",
            {"email": "test@example.com", "password": "strongpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email="test@example.com").exists())

    def test_user_login(self):
        User.objects.create_user(
            username="login@example.com",
            email="login@example.com",
            password="mypassword",
        )
        response = self.client.post(
            "/api/auth/login/",
            {"email": "login@example.com", "password": "mypassword"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_registration_duplicate_email(self):
        User.objects.create_user(
            username="dup@example.com",
            email="dup@example.com",
            password="pass1234",
        )
        response = self.client.post(
            "/api/auth/register/",
            {"email": "dup@example.com", "password": "pass1234"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_short_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {"email": "short@example.com", "password": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_rate_limited_after_5_attempts(self):
        User.objects.create_user(
            username="ratelimit@example.com",
            email="ratelimit@example.com",
            password="correct_password",
        )
        client = APIClient(REMOTE_ADDR="10.0.0.1")
        for _ in range(5):
            client.post(
                "/api/auth/login/",
                {"email": "ratelimit@example.com", "password": "wrong_password"},
                format="json",
                REMOTE_ADDR="10.0.0.1",
            )
        response = client.post(
            "/api/auth/login/",
            {"email": "ratelimit@example.com", "password": "wrong_password"},
            format="json",
            REMOTE_ADDR="10.0.0.1",
        )
        self.assertIn(response.status_code, (status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_403_FORBIDDEN))

    def test_logout_blacklists_refresh_token(self):
        User.objects.create_user(
            username="logout@example.com",
            email="logout@example.com",
            password="mypassword",
        )
        login_res = self.client.post(
            "/api/auth/login/",
            {"email": "logout@example.com", "password": "mypassword"},
            format="json",
        )
        refresh_token = login_res.data["refresh"]

        logout_res = self.client.post(
            "/api/auth/logout/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)

        refresh_res = self.client.post(
            "/api/auth/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_401_UNAUTHORIZED)

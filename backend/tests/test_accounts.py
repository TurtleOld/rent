from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django_ratelimit.core import get_usage
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.views import LOGIN_RATE_LIMIT, LOGIN_RATE_LIMIT_GROUP

User = get_user_model()


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class AuthTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

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
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["detail"], "Слишком много попыток входа. Попробуйте позже.")

    def test_login_rate_limit_response_has_retry_after(self):
        client = APIClient(REMOTE_ADDR="10.0.0.2")
        payload = {"email": "nobody@example.com", "password": "wrong_password"}
        for _ in range(5):
            client.post("/api/auth/login/", payload, format="json", REMOTE_ADDR="10.0.0.2")
        response = client.post(
            "/api/auth/login/", payload, format="json", REMOTE_ADDR="10.0.0.2"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        retry_after = response.headers.get("Retry-After")
        self.assertIsNotNone(retry_after)
        self.assertTrue(retry_after.isdigit(), retry_after)
        self.assertGreaterEqual(int(retry_after), 1)
        self.assertLessEqual(int(retry_after), 60)

    def test_login_rate_limit_check_does_not_increment_counter(self):
        client = APIClient(REMOTE_ADDR="10.0.0.3")
        payload = {"email": "nobody@example.com", "password": "wrong_password"}
        for _ in range(6):
            client.post("/api/auth/login/", payload, format="json", REMOTE_ADDR="10.0.0.3")

        # Получение времени до конца окна не должно засчитывать седьмую попытку.
        request = RequestFactory().post("/api/auth/login/", REMOTE_ADDR="10.0.0.3")
        usage = get_usage(
            request,
            group=LOGIN_RATE_LIMIT_GROUP,
            key="ip",
            rate=LOGIN_RATE_LIMIT,
            increment=False,
        )
        self.assertEqual(usage["count"], 6)

    def test_login_rate_limit_is_per_real_client_ip(self):
        # All requests come from the same proxy REMOTE_ADDR; only X-Real-IP differs.
        client = APIClient(REMOTE_ADDR="172.18.0.5")
        payload = {"email": "nobody@example.com", "password": "wrong_password"}
        for _ in range(6):
            client.post("/api/auth/login/", payload, format="json", HTTP_X_REAL_IP="1.1.1.1")
        response = client.post("/api/auth/login/", payload, format="json", HTTP_X_REAL_IP="2.2.2.2")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

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


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class AdminLoginRateLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="correct_password",
        )

    def _login(self, client, *, password="wrong_password", real_ip):
        return client.post(
            "/admin/login/",
            {
                "username": "admin@example.com",
                "password": password,
                "next": "/admin/",
            },
            REMOTE_ADDR="172.18.0.5",
            HTTP_X_REAL_IP=real_ip,
        )

    def test_admin_login_blocked_after_5_failed_attempts(self):
        client = Client()
        for _ in range(5):
            self._login(client, real_ip="10.0.0.1")

        response = self._login(client, password="correct_password", real_ip="10.0.0.1")
        self.assertIn(
            response.status_code,
            (status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_403_FORBIDDEN),
        )

    def test_admin_login_rate_limit_is_per_real_client_ip(self):
        client = Client()
        for _ in range(6):
            self._login(client, real_ip="1.1.1.1")

        response = self._login(client, password="correct_password", real_ip="2.2.2.2")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

    def test_admin_login_get_requests_are_not_limited(self):
        client = Client()
        for _ in range(10):
            client.get(
                "/admin/login/",
                REMOTE_ADDR="172.18.0.5",
                HTTP_X_REAL_IP="3.3.3.3",
            )

        response = self._login(client, password="correct_password", real_ip="3.3.3.3")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

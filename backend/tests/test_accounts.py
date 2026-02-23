from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class UserRegistrationTest(TestCase):
    def setUp(self):
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

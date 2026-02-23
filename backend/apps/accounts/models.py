from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    # username is kept to satisfy AbstractUser's DB requirement,
    # but email is the actual login credential.
    REQUIRED_FIELDS = ["username"]

    def __str__(self) -> str:
        return self.email

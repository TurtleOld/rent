from django.contrib.auth.models import User
from django.db import models


class Profile(models.Model):
    """Модель профиля пользователя"""

    user: models.OneToOneField[User, User] = models.OneToOneField(
        User, on_delete=models.CASCADE, verbose_name="Пользователь"
    )
    phone: models.CharField = models.CharField(
        max_length=20, blank=True, verbose_name="Телефон"
    )
    address: models.TextField = models.TextField(blank=True, verbose_name="Адрес")
    birth_date: models.DateField = models.DateField(
        null=True, blank=True, verbose_name="Дата рождения"
    )
    avatar: models.ImageField = models.ImageField(
        upload_to="avatars/", null=True, blank=True, verbose_name="Аватар"
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, verbose_name="Дата создания"
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True, verbose_name="Дата обновления"
    )

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"

    def __str__(self) -> str:
        return f"Профиль {self.user.username}"


def get_or_create_profile(user: User) -> Profile:
    """Получить или создать профиль для пользователя"""
    try:
        return user.profile  # type: ignore[attr-defined]
    except Profile.DoesNotExist:
        return Profile.objects.create(user=user)


User.add_to_class("get_or_create_profile", get_or_create_profile)

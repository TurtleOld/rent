from typing import cast

from django.contrib.auth.models import User
from django.db import models


class Profile(models.Model):
    """Модель профиля пользователя"""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, verbose_name="Пользователь"
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name="Телефон")
    address = models.TextField(blank=True, verbose_name="Адрес")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    avatar = models.ImageField(
        upload_to="avatars/", null=True, blank=True, verbose_name="Аватар"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"

    def __str__(self) -> str:
        return f"Профиль {self.user.username}"


# Расширяем модель User для автоматического создания профиля
def get_or_create_profile(user: User) -> Profile:
    """Получить или создать профиль для пользователя"""
    try:
        return cast(Profile, user.profile)
    except Profile.DoesNotExist:
        return cast(Profile, Profile.objects.create(user=user))


# Добавляем метод к модели User
User.add_to_class("get_or_create_profile", get_or_create_profile)

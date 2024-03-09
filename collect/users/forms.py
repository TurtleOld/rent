from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import AbstractUser
from django.forms import forms, CharField


class UserLoginForm(AuthenticationForm):
    username = AbstractUser.username
    password = AbstractUser.password
    fields = ['username', 'password']


class ForgotPasswordForm(forms.Form):
    username = CharField(
        label='Имя пользователя',
    )

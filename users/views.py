from typing import Any, cast

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from .forms import ProfileUpdateForm, UserLoginForm, UserRegistrationForm
from .models import Profile


def register(request: HttpRequest) -> HttpResponse:
    """Представление для регистрации пользователя"""
    if request.user.is_authenticated:
        return redirect("epd_parser:home")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Создаем профиль для нового пользователя
            user.get_or_create_profile()
            login(request, user)
            messages.success(request, "Регистрация прошла успешно!")
            return redirect("epd_parser:home")
        else:
            messages.error(
                request, "Ошибка при регистрации. Проверьте введенные данные."
            )
    else:
        form = UserRegistrationForm()

    return render(request, "users/register.html", {"form": form})


def user_login(request: HttpRequest) -> HttpResponse:
    """Представление для входа пользователя"""
    if request.user.is_authenticated:
        return redirect("epd_parser:home")

    if request.method == "POST":
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user is not None:
                # Убеждаемся, что у пользователя есть профиль
                user.get_or_create_profile()
                login(request, user)
                messages.success(request, f"Добро пожаловать, {user.username}!")
                return redirect("epd_parser:home")
            else:
                messages.error(request, "Неверное имя пользователя или пароль.")
        else:
            messages.error(request, "Ошибка при входе. Проверьте введенные данные.")
    else:
        form = UserLoginForm()

    return render(request, "users/login.html", {"form": form})


@login_required  # type: ignore[misc]
def user_logout(request: HttpRequest) -> HttpResponse:
    """Представление для выхода пользователя"""
    logout(request)
    messages.success(request, "Вы успешно вышли из системы.")
    return redirect("epd_parser:home")


@login_required  # type: ignore[misc]
def profile(request: HttpRequest) -> HttpResponse:
    """Представление для просмотра профиля пользователя"""
    # Убеждаемся, что у пользователя есть профиль
    request.user.get_or_create_profile()
    return render(request, "users/profile.html")


@login_required  # type: ignore[misc]
def profile_edit(request: HttpRequest) -> HttpResponse:
    """Представление для редактирования профиля пользователя"""
    # Убеждаемся, что у пользователя есть профиль
    profile = request.user.get_or_create_profile()

    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Профиль успешно обновлен!")
            return redirect("users:profile")
        else:
            messages.error(request, "Ошибка при обновлении профиля.")
    else:
        form = ProfileUpdateForm(instance=profile)

    return render(request, "users/profile_edit.html", {"form": form})


class UserLoginView(LoginView):
    """Класс-представление для входа пользователя"""

    form_class = UserLoginForm
    template_name = "users/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        return cast(str, reverse_lazy("epd_parser:home"))

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(self.request, "Ошибка при входе. Проверьте введенные данные.")
        return cast(HttpResponse, super().form_invalid(form))


class UserRegistrationView(CreateView):
    """Класс-представление для регистрации пользователя"""

    form_class = UserRegistrationForm
    template_name = "users/register.html"
    success_url = reverse_lazy("epd_parser:home")
    redirect_authenticated_user = True

    def form_valid(self, form: Any) -> HttpResponse:
        response = cast(HttpResponse, super().form_valid(form))
        # Создаем профиль для нового пользователя
        self.object.get_or_create_profile()
        login(self.request, self.object)
        messages.success(self.request, "Регистрация прошла успешно!")
        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(
            self.request, "Ошибка при регистрации. Проверьте введенные данные."
        )
        return cast(HttpResponse, super().form_invalid(form))


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Класс-представление для обновления профиля"""

    model = Profile
    form_class = ProfileUpdateForm
    template_name = "users/profile_edit.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset: Any = None) -> Profile:
        return cast(Profile, self.request.user.get_or_create_profile())

    def form_valid(self, form: Any) -> HttpResponse:
        messages.success(self.request, "Профиль успешно обновлен!")
        return cast(HttpResponse, super().form_valid(form))

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(self.request, "Ошибка при обновлении профиля.")
        return cast(HttpResponse, super().form_invalid(form))

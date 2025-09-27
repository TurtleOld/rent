from typing import Any, cast

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView

from .forms import ProfileUpdateForm, UserLoginForm, UserRegistrationForm
from .models import Profile

HOME_URL = "epd_parser:home"


def register(request: HttpRequest) -> HttpResponse:
    """Представление для регистрации пользователя"""
    if request.user.is_authenticated:
        return redirect(HOME_URL)

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.get_or_create_profile()
            login(request, user)
            messages.success(request, "Регистрация прошла успешно!")
            return redirect(HOME_URL)
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
        return redirect(HOME_URL)

    if request.method == "POST":
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(username=username, password=password)
            if user is not None:
                user.get_or_create_profile()
                login(request, user)
                messages.success(request, f"Добро пожаловать, {user.username}!")
                return redirect(HOME_URL)
            else:
                messages.error(request, "Неверное имя пользователя или пароль.")
        else:
            messages.error(request, "Ошибка при входе. Проверьте введенные данные.")
    else:
        form = UserLoginForm()

    return render(request, "users/login.html", {"form": form})


@login_required
def user_logout(request: HttpRequest) -> HttpResponse:
    """Представление для выхода пользователя"""
    logout(request)
    messages.success(request, "Вы успешно вышли из системы.")
    return redirect("epd_parser:home")


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """Представление для просмотра профиля пользователя"""
    request.user.get_or_create_profile()
    return render(request, "users/profile.html")


@login_required
def profile_edit(request: HttpRequest) -> HttpResponse:
    """Представление для редактирования профиля пользователя"""
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
        return cast(str, reverse_lazy(HOME_URL))

    def form_valid(self, form: Any) -> HttpResponse:
        response = super().form_valid(form)
        self.request.user.get_or_create_profile()  # type: ignore[attr-defined]
        messages.success(
            self.request, f"Добро пожаловать, {self.request.user.username}!"  # type: ignore[attr-defined]
        )
        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(self.request, "Ошибка при входе. Проверьте введенные данные.")
        return cast(HttpResponse, super().form_invalid(form))


class UserRegistrationView(CreateView):
    """Класс-представление для регистрации пользователя"""

    form_class = UserRegistrationForm
    template_name = "users/register.html"
    success_url = reverse_lazy(HOME_URL)
    redirect_authenticated_user = True

    def form_valid(self, form: Any) -> HttpResponse:
        response = super().form_valid(form)
        self.object.get_or_create_profile()  # type: ignore[attr-defined]
        login(self.request, self.object)
        messages.success(self.request, "Регистрация прошла успешно!")
        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(
            self.request, "Ошибка при регистрации. Проверьте введенные данные."
        )
        return cast(HttpResponse, super().form_invalid(form))


class UserLogoutView(LogoutView):
    """Класс-представление для выхода пользователя"""

    def get_next_page(self) -> str:
        messages.success(self.request, "Вы успешно вышли из системы.")
        return reverse_lazy(HOME_URL)


class ProfileView(LoginRequiredMixin, TemplateView):
    """Класс-представление для просмотра профиля пользователя"""

    template_name = "users/profile.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        self.request.user.get_or_create_profile()  # type: ignore[attr-defined]
        return context


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Класс-представление для обновления профиля"""

    model = Profile
    form_class = ProfileUpdateForm
    template_name = "users/profile_edit.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset: Any = None) -> Profile:
        return self.request.user.get_or_create_profile()  # type: ignore[attr-defined]

    def form_valid(self, form: Any) -> HttpResponse:
        messages.success(self.request, "Профиль успешно обновлен!")
        return super().form_valid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(self.request, "Ошибка при обновлении профиля.")
        return super().form_invalid(form)

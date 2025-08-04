from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import UpdateView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from .forms import UserLoginForm, ProfileUpdateForm
from .models import Profile


class UserLoginView(LoginView):
    """Класс-представление для входа пользователя"""

    form_class = UserLoginForm
    template_name = "users/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("epd_parser:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        # Убеждаемся, что у пользователя есть профиль
        self.request.user.get_or_create_profile()
        messages.success(
            self.request, f"Добро пожаловать, {self.request.user.username}!"
        )
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Ошибка при входе. Проверьте введенные данные.")
        return super().form_invalid(form)


class UserLogoutView(LogoutView):
    """Класс-представление для выхода пользователя"""

    def get_next_page(self):
        messages.success(self.request, "Вы успешно вышли из системы.")
        return reverse_lazy("epd_parser:home")


class ProfileView(LoginRequiredMixin, TemplateView):
    """Класс-представление для просмотра профиля пользователя"""

    template_name = "users/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Убеждаемся, что у пользователя есть профиль
        self.request.user.get_or_create_profile()
        return context


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """Класс-представление для редактирования профиля пользователя"""

    model = Profile
    form_class = ProfileUpdateForm
    template_name = "users/profile_edit.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        return self.request.user.get_or_create_profile()

    def form_valid(self, form):
        messages.success(self.request, "Профиль успешно обновлен!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Ошибка при обновлении профиля.")
        return super().form_invalid(form)

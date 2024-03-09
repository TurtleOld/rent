from django.contrib import messages
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from collect.users.forms import UserLoginForm


class IndexView(TemplateView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('rent:list')
        return redirect('login')


class LoginUser(SuccessMessageMixin, LoginView):
    model = AbstractUser
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = 'Авторизация прошла успешно'
    next_page = '/rent'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['button_text'] = 'Войти'
        context['user_login_form'] = UserLoginForm()
        return context


class LogoutUser(LogoutView, SuccessMessageMixin):
    def dispatch(self, request, *args, **kwargs):
        messages.add_message(
            request,
            messages.SUCCESS,
            'Выход прошёл успешно!',
        )
        return super().dispatch(request, *args, **kwargs)

from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    # Функциональные представления
    path("register/", views.register, name="register"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    # Класс-представления (альтернативный вариант)
    # path('register/', views.UserRegistrationView.as_view(), name='register'),
    # path('login/', views.UserLoginView.as_view(), name='login'),
    # path('profile/edit/', views.ProfileUpdateView.as_view(), name='profile_edit'),
]

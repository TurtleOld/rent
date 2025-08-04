# Система пользователей EPD Parser

## Обзор

Приложение `users` предоставляет полную систему аутентификации и управления пользователями для проекта EPD Parser.

## Возможности

### 🔐 Аутентификация
- **Регистрация пользователей** - создание новых аккаунтов
- **Вход в систему** - авторизация существующих пользователей
- **Выход из системы** - безопасное завершение сессии

### 👤 Управление профилем
- **Просмотр профиля** - отображение информации о пользователе
- **Редактирование профиля** - обновление личных данных
- **Загрузка аватара** - возможность добавить фото профиля

### 🛡️ Безопасность
- **Ограничение доступа** - все функции EPD Parser требуют авторизации
- **Валидация данных** - проверка корректности введенной информации
- **Защита от дублирования** - уникальность email адресов

## Структура приложения

### Модели (`users/models.py`)
```python
class Profile(models.Model):
    """Расширенная модель профиля пользователя"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    birth_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Формы (`users/forms.py`)
- `UserRegistrationForm` - форма регистрации
- `UserLoginForm` - форма входа
- `ProfileUpdateForm` - форма редактирования профиля

### Представления (`users/views.py`)
- `register()` - регистрация пользователя
- `user_login()` - вход в систему
- `user_logout()` - выход из системы
- `profile()` - просмотр профиля
- `profile_edit()` - редактирование профиля

### URL маршруты (`users/urls.py`)
```
/users/register/     - Регистрация
/users/login/        - Вход в систему
/users/logout/       - Выход из системы
/users/profile/      - Профиль пользователя
/users/profile/edit/ - Редактирование профиля
```

## Использование

### Для неавторизованных пользователей
1. При переходе на главную страницу отображается приветственная информация
2. Доступны кнопки "Войти" и "Регистрация"
3. Все функции EPD Parser недоступны

### Для авторизованных пользователей
1. Полный доступ ко всем функциям системы
2. В навигации отображается имя пользователя с выпадающим меню
3. Возможность просмотра и редактирования профиля

## Настройки безопасности

### В `settings.py`:
```python
# Authentication settings
LOGIN_REDIRECT_URL = "/"           # Перенаправление после входа
LOGOUT_REDIRECT_URL = "/"          # Перенаправление после выхода
LOGIN_URL = "/users/login/"        # URL страницы входа
```

### Ограничения доступа
Все представления EPD Parser защищены декоратором `@login_required` или миксином `LoginRequiredMixin`:

```python
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

# Для функциональных представлений
@login_required
def my_view(request):
    pass

# Для класс-представлений
class MyView(LoginRequiredMixin, View):
    pass
```

## Шаблоны

### Основные шаблоны:
- `templates/users/register.html` - страница регистрации
- `templates/users/login.html` - страница входа
- `templates/users/profile.html` - профиль пользователя
- `templates/users/profile_edit.html` - редактирование профиля

### Интеграция с основным шаблоном:
В `templates/base.html` добавлена условная навигация:
```html
{% if user.is_authenticated %}
    <!-- Меню для авторизованных пользователей -->
{% else %}
    <!-- Кнопки входа и регистрации -->
{% endif %}
```

## Администрирование

### Админка Django
- Расширенная админка для пользователей с профилем
- Отдельная админка для профилей
- Инлайн-редактирование профиля в админке пользователя

### Создание суперпользователя
```bash
uv run python manage.py createsuperuser
```

## Тестирование

### Создание тестового пользователя
```python
from django.contrib.auth.models import User
User.objects.create_user('testuser', 'test@example.com', 'testpass123')
```

### Проверка работы системы
1. Запустите сервер: `uv run python manage.py runserver`
2. Откройте http://127.0.0.1:8000/
3. Попробуйте зарегистрироваться и войти в систему
4. Проверьте доступ к функциям EPD Parser

## Зависимости

- `django-crispy-forms` - для красивого отображения форм
- `crispy-bootstrap5` - Bootstrap 5 стили для форм
- `python-decouple` - для управления настройками

## Миграции

Приложение создает автоматически профиль для каждого нового пользователя через сигналы Django:

```python
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
```

## Безопасность

- Пароли хешируются с использованием встроенных валидаторов Django
- CSRF защита включена для всех форм
- Сессии управляются через Django Session Framework
- Все URL защищены от несанкционированного доступа 
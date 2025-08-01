# Быстрый старт - EPD Parser

## 🚀 Запуск с Docker (рекомендуется)

### 1. Клонирование и запуск
```bash
# Клонируйте репозиторий
git clone <repository-url>
cd rent

# Запустите с Docker Compose
docker-compose up -d

# Примените миграции
docker-compose exec web python manage.py migrate

# Создайте суперпользователя
docker-compose exec web python manage.py createsuperuser

# Соберите статические файлы
docker-compose exec web python manage.py collectstatic --noinput
```

### 2. Доступ к приложению
- **Веб-интерфейс**: http://localhost:8000
- **Админка**: http://localhost:8000/admin

## 🔧 Запуск без Docker

### 1. Установка зависимостей
```bash
# Установите uv
pip install uv

# Установите зависимости проекта
uv pip install -e .
```

### 2. Настройка базы данных
```bash
# Создайте базу данных PostgreSQL
createdb utility_parser

# Примените миграции
python manage.py migrate

# Создайте суперпользователя
python manage.py createsuperuser
```

### 3. Запуск сервера
```bash
python manage.py runserver
```

## 📋 Использование

1. **Загрузка документа**: Перейдите на http://localhost:8000/upload/ и загрузите PDF файл ЕПД
2. **Просмотр документов**: Список всех документов на главной странице
3. **Поиск**: Используйте поиск по ФИО, адресу или лицевому счету
4. **Статистика**: Просмотр аналитики по документам

## 🛠 Разработка

### Установка инструментов разработки
```bash
uv pip install -e ".[dev]"
```

### Запуск проверок качества кода
```bash
# Форматирование
ruff format .
black .
isort .

# Проверка стиля
ruff check .

# Проверка типов
mypy .

# Тесты
pytest
```

### Полезные команды
```bash
# Создание миграций
python manage.py makemigrations

# Применение миграций
python manage.py migrate

# Создание суперпользователя
python manage.py createsuperuser

# Сбор статических файлов
python manage.py collectstatic
```

## 🔍 Структура проекта

```
rent/
├── utility_parser/          # Основной проект Django
├── epd_parser/             # Приложение для парсинга ЕПД
├── templates/              # HTML шаблоны
├── tests/                  # Тесты
├── Dockerfile              # Docker образ
├── docker-compose.yml      # Docker Compose
├── pyproject.toml         # Конфигурация проекта
└── README.md              # Подробная документация
```

## 🆘 Поддержка

При возникновении проблем:
1. Проверьте логи: `docker-compose logs web`
2. Убедитесь, что PostgreSQL запущен
3. Проверьте настройки в `env.example`
4. Создайте Issue с описанием проблемы

## 📚 Дополнительная документация

Подробная документация доступна в файле [README.md](README.md). 
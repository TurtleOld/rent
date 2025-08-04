# EPD Parser - Система управления документами ЕПД

> **⚠️ ВНИМАНИЕ**: Данный проект был разработан с использованием искусственного интеллекта. Все риски, связанные с использованием, модификацией и развертыванием проекта, полностью ложатся на пользователя. Проект предназначен для self-hosted развертывания.

Современное Django приложение для автоматического парсинга и хранения данных из документов ЕПД (Единый платежный документ) с использованием современных технологий.

## 🚀 Возможности

- **Автоматический парсинг данных**: ФИО, адрес, лицевой счет, период оплаты, суммы
- **Детальная информация об услугах**: объем, ед.изм., тариф, долг, оплачено, итого
- **Современный веб-интерфейс** с Bootstrap 5
- **Docker контейнеризация** для простого развертывания
- **PostgreSQL** для надежного хранения данных
- **Строгая типизация** с mypy
- **Качество кода** с ruff, isort
- **Безопасность**: валидация файлов, защита от XSS, CSRF

## 🛠 Технологии

- **Backend**: Django 5.2.4, Python 3.13+
- **WSGI Server**: Granian (высокопроизводительный сервер на Rust)
- **Database**: PostgreSQL 15 (с fallback на SQLite)
- **PDF Handling**: PDF file upload and validation
- **Package Manager**: uv
- **Code Quality**: ruff, mypy, isort
- **Frontend**: Bootstrap 5, JavaScript
- **Containerization**: Docker, Docker Compose

## 📋 Требования

- Python 3.13+
- Docker и Docker Compose (опционально)
- PostgreSQL 15 (опционально, по умолчанию используется SQLite)

## 🚀 Быстрый старт с Docker

### 1. Клонирование репозитория

```bash
git clone https://github.com/TurtleOld/rent.git
cd rent
```

### 2. Запуск с Docker Compose (Development)

```bash
# Создание и запуск контейнеров
docker compose up -d

# Применение миграций
docker compose exec web python manage.py migrate

# Создание суперпользователя
docker compose exec web python manage.py createsuperuser

# Сбор статических файлов
docker compose exec web python manage.py collectstatic --noinput
```

### 3. Доступ к приложению

- **Веб-интерфейс**: http://localhost:8000
- **Админка**: http://localhost:8000/admin
- **База данных**: localhost:5432


## 🚀 Production развертывание

### Использование Makefile (рекомендуется)

```bash
# Сбор production образа
make prod-build

# Запуск production версии
make prod-up

# Просмотр логов
make prod-logs

# Остановка production версии
make prod-down
```

### Ручное развертывание

#### 1. Настройка переменных окружения

```bash
# Скопируйте файл с переменными
cp env.prod.example .env.prod

# Отредактируйте .env.prod
SECRET_KEY=your-super-secret-key-change-in-production
DEBUG=False
ALLOWED_HOSTS=your-domain.com,localhost,127.0.0.1
```

#### 2. Запуск production версии

```bash
# Сбор и запуск
docker-compose -f docker-compose.prod.yml up -d --build

# Или с переменными окружения
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

### Особенности Production версии

- **Granian WSGI сервер**: Высокопроизводительный ASGI/WSGI сервер на Rust
- **Автоматические миграции**: Применяются при запуске контейнера
- **Статические файлы**: Автоматически собираются при запуске
- **PostgreSQL**: Настроена для production использования
- **Health checks**: Проверка готовности базы данных
- **Restart policy**: Автоматический перезапуск при сбоях

### Примеры использования

#### Запуск конкретной версии
```bash
export IMAGE_TAG=v1.0.0
docker-compose -f docker-compose.prod.yml --env-file .env.prod up
```

#### Запуск с кастомными настройками
```bash
export GITHUB_REPOSITORY=mycompany/rent
export IMAGE_TAG=main
export SECRET_KEY=my-super-secret-key
docker-compose -f docker-compose.prod.yml --env-file .env.prod up
```

## 🔧 Установка без Docker

### 1. Установка зависимостей

```bash
# Установка uv
pip install uv

# Установка зависимостей проекта
uv pip install -e .
```

### 2. Настройка базы данных

```bash
# Применение миграций (SQLite будет создан автоматически)
python manage.py migrate

# Создание суперпользователя
python manage.py createsuperuser
```

**Примечание**: По умолчанию используется SQLite. Для использования PostgreSQL установите переменные окружения:
```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=utility_parser
export DB_USER=postgres
export DB_PASSWORD=postgres
```

### 3. Запуск сервера

```bash
python manage.py runserver
```

## 📁 Структура проекта

```
rent/
├── utility_parser/          # Основной проект Django
│   ├── settings.py         # Настройки проекта
│   ├── urls.py            # Главные URL
│   └── wsgi.py            # WSGI конфигурация
├── epd_parser/            # Приложение для управления ЕПД
│   ├── models.py          # Модели данных
│   ├── views.py           # Представления
│   ├── forms.py           # Формы
│   ├── ocr_parser.py      # OCR парсер (заглушка)
│   ├── admin.py           # Админка
│   └── urls.py            # URL приложения
├── templates/             # HTML шаблоны
├── static/               # Статические файлы
├── media/                # Загруженные файлы
├── Dockerfile            # Docker образ
├── docker-compose.yml    # Docker Compose
├── pyproject.toml        # Конфигурация проекта
└── README.md            # Документация
```

## 🗄 Модели данных

### EpdDocument
Основная модель для хранения информации о документе ЕПД:
- ФИО, адрес, лицевой счет
- Период оплаты и срок оплаты
- Общие суммы (с учетом и без учета страхования)
- Ссылка на оригинальный PDF файл

### ServiceCharge
Модель для хранения информации об услугах:
- Название услуги
- Объем и тариф
- Суммы: начислено, долг, оплачено, итого
- Порядок отображения

## 🔍 Использование

### 1. Загрузка документа

1. Перейдите на страницу "Загрузить"
2. Выберите PDF файл документа ЕПД
3. Система автоматически извлечет данные из документа
4. Проверьте и при необходимости отредактируйте данные
5. Сохраните документ

### 2. Просмотр документов

- **Список документов**: просмотр всех загруженных документов
- **Детальный просмотр**: полная информация о документе и услугах
- **Поиск**: поиск по ФИО, адресу, лицевому счету
- **Статистика**: общая статистика по документам

### 3. Управление данными

- **Редактирование**: изменение данных документа
- **Удаление**: удаление документа и связанных файлов
- **Скачивание**: скачивание оригинального PDF

## 🛡 Безопасность

- Валидация загружаемых файлов
- Защита от XSS и CSRF атак
- Безопасная обработка файлов
- Валидация данных на всех уровнях
- Логирование операций

## 🧪 Разработка

### Установка инструментов разработки

```bash
uv pip install -e ".[dev]"
```

### Запуск проверок качества кода

```bash
# Форматирование кода
make format

# Проверка стиля кода и типов
make lint

# Запуск тестов
make test

# Очистка кэша
make clean
```

### Создание миграций

```bash
python manage.py makemigrations
python manage.py migrate
```

## 📊 Мониторинг и логирование

Приложение настроено с подробным логированием:
- Логи Django в `logs/django.log`
- Логи парсера в консоли и файле
- Обработка ошибок с уведомлениями

## 🔧 Конфигурация

### Переменные окружения

```bash
# База данных
DB_NAME=utility_parser
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Настройки системы

Система настроена для работы с типичными документами ЕПД. При необходимости можно настроить валидацию данных в `epd_parser/forms.py`.

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для новой функции
3. Внесите изменения с соблюдением стандартов кода
4. Добавьте тесты
5. Создайте Pull Request

## 📄 Лицензия

MIT License

## 🆘 Поддержка

При возникновении проблем:
1. Проверьте логи в `logs/django.log`
2. Убедитесь в корректности PDF файла
3. Проверьте настройки базы данных
4. Создайте Issue с описанием проблемы

## 🔄 Обновления

Для обновления приложения:

```bash
# Остановка контейнеров
docker-compose down

# Обновление кода
git pull

# Пересборка и запуск
docker-compose up -d --build

# Применение миграций
docker-compose exec web python manage.py migrate
``` 
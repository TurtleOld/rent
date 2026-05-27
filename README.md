# Учёт платежей ЖКХ

MVP для загрузки и отслеживания коммунальных квитанций с автоматическим извлечением данных через AI API.

## Быстрый старт

### 1. Скопировать и заполнить .env

```bash
cp .env.example .env
```

Обязательно заполнить:

| Переменная | Описание |
|---|---|
| `SECRET_KEY` | Секретный ключ Django (50+ случайных символов) |
| `POSTGRES_PASSWORD` | Пароль БД — **обязательно сгенерировать в prod** |

Сгенерировать SECRET_KEY и пароль БД:
```bash
python -c "import secrets; print(secrets.token_hex(50))"
```

> **Важно**: никогда не оставляйте `POSTGRES_PASSWORD=changeme_in_prod` в production.

### 2. Запустить

```bash
docker compose up --build
```

Приложение будет доступно на [http://localhost](http://localhost).

### 3. Создать суперпользователя (опционально)

```bash
docker compose exec backend python manage.py createsuperuser
```

Панель администратора: [http://localhost/admin](http://localhost/admin)

---

## Переменные окружения

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `SECRET_KEY` | — | Секретный ключ Django (обязательно) |
| `DEBUG` | `False` | Режим отладки |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Разрешённые хосты |
| `POSTGRES_USER` | `rent` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | — | Пароль PostgreSQL (**сгенерировать в prod**) |
| `POSTGRES_DB` | `rent` | Имя базы данных PostgreSQL |
| `DATABASE_URL` | — | URL базы данных (dj-database-url формат) |
| `REDIS_URL` | `redis://redis:6379/0` | URL Redis (Celery broker) |
| `MEDIA_ROOT` | `/app/media` | Путь для хранения PDF-файлов |
| `ACCESS_TOKEN_LIFETIME_MINUTES` | `60` | Время жизни JWT access-токена |
| `REFRESH_TOKEN_LIFETIME_DAYS` | `7` | Время жизни JWT refresh-токена |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS (для локальной разработки) |

---

## API

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/api/auth/register/` | Регистрация |
| `POST` | `/api/auth/login/` | Вход (возвращает JWT) |
| `POST` | `/api/auth/refresh/` | Обновление токена |
| `GET` | `/api/invoices/` | Список квитанций (только свои) |
| `POST` | `/api/invoices/upload/` | Загрузить PDF |
| `GET` | `/api/invoices/{id}/` | Детали квитанции |
| `PATCH` | `/api/invoices/{id}/` | Редактировать извлечённые поля |
| `GET` | `/api/invoices/{id}/payments/` | Список платежей |
| `POST` | `/api/invoices/{id}/payments/` | Добавить платёж |

---

## Запуск тестов

```bash
docker compose exec backend python manage.py test tests
```

---

## Локальная разработка (без Docker)

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Создать .env с DATABASE_URL для локального postgres
python manage.py migrate
python manage.py runserver
```

### Celery worker

```bash
cd backend
celery -A config worker -l info
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend доступен на [http://localhost:3000](http://localhost:3000), API-запросы проксируются на `http://localhost:8000` через `next.config.ts`.

---

## Архитектура

```
nginx:80
  /api/*    → backend:8000  (Django + DRF + SimpleJWT)
  /admin/*  → backend:8000
  /media/*  → shared Docker volume (PDF-файлы)
  /*        → frontend:3000 (Next.js standalone)

backend:8000 + celery worker
  Читают/пишут PostgreSQL и shared media volume

celery worker
  Обрабатывает PDF асинхронно:
  1. Читает PDF из хранилища
  2. Отправляет в AI API (POST multipart)
  3. Валидирует JSON-ответ
  4. Сохраняет Invoice + LineItems
  5. Обновляет статус: processed | failed
```

---

## Структура проекта

```
rent/
├── .env.example
├── docker-compose.yml
├── nginx/nginx.conf
├── backend/
│   ├── config/           # Django settings, URLs, Celery
│   ├── apps/
│   │   ├── accounts/     # User модель + JWT auth
│   │   ├── invoices/     # Invoice, LineItem, Celery task
│   │   └── payments/     # Payment модель
│   └── tests/
└── frontend/
    └── src/
        ├── app/          # Next.js App Router
        └── lib/          # API-клиент, управление токенами
```

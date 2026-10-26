# Учёт квитанций ЖКХ

MVP для загрузки и отслеживания коммунальных квитанций с автоматическим извлечением данных: PDF разбирается локально через pdfplumber и регулярные выражения, без внешних AI-сервисов.

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

## Обновление продакшена: владелец тома media

Бэкенд и Celery работают от пользователя `app` с uid/gid `10001`. Новый пустой том `media_files` получает владельца из образа автоматически. Существующий том, файлы на котором созданы старым образом от root, нужно один раз перевести на `app` — иначе приложение не сможет записывать новые и удалять старые PDF:

```bash
docker compose -f docker-compose.prod.yml run --rm --user root backend chown -R 10001:10001 /app/media
docker compose -f docker-compose.prod.yml up -d backend celery
```

Проверить, что контейнеры запустились от нужного пользователя:

```bash
docker compose -f docker-compose.prod.yml exec backend id -u
docker compose -f docker-compose.prod.yml exec celery id -u
```

Обе команды должны вывести `10001`.

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
| `ACCESS_TOKEN_LIFETIME_MINUTES` | `60` | Время жизни JWT access-токена и access-cookie фронтенда |
| `REFRESH_TOKEN_LIFETIME_DAYS` | `7` | Время жизни JWT refresh-токена и refresh-cookie фронтенда |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS (для локальной разработки) |

`ACCESS_TOKEN_LIFETIME_MINUTES` и `REFRESH_TOKEN_LIFETIME_DAYS` читают и бэкенд, и фронтенд: Django задаёт срок жизни JWT, а прокси ставит httpOnly-cookie с тем же сроком. Значения нужно менять до запуска обоих контейнеров; например, при `REFRESH_TOKEN_LIFETIME_DAYS=30` сессия живёт 30 дней, а не 7. В локальной разработке без Docker Next.js не читает корневой `.env` — те же переменные нужно задать в `frontend/.env`.

---

## API

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/api/auth/login/` | Вход через прокси (ставит JWT в httpOnly-cookie) |
| `POST` | `/api/auth/refresh/` | Обновление токена |
| `POST` | `/api/auth/logout/` | Выход (отзывает refresh-токен) |
| `GET` | `/api/invoices/` | Список квитанций (только свои) |
| `POST` | `/api/invoices/upload/` | Загрузить PDF |
| `GET` | `/api/invoices/{id}/` | Детали квитанции |
| `DELETE` | `/api/invoices/{id}/` | Удалить квитанцию |
| `GET` | `/api/invoices/{id}/file/` | Скачать исходный PDF |
| `POST` | `/api/invoices/{id}/reparse/` | Повторно разобрать PDF |

---

## Запуск тестов

```bash
docker compose exec backend python manage.py test tests
```

---

## Очистка осиротевших PDF

После удаления квитанций старые PDF могли остаться в `media/invoices/`. Команда находит файлы, на которые не ссылается ни одна квитанция, и пропускает файлы моложе часа: они могут принадлежать загрузке, запись о которой ещё не создана.

Сначала посмотрите список, ничего не удаляя:

```bash
docker compose exec backend python manage.py cleanup_orphan_pdfs
```

Затем удалите найденные файлы:

```bash
docker compose exec backend python manage.py cleanup_orphan_pdfs --delete
```

Если удалить какой-то файл не удалось, команда продолжит работу, выведет ошибку и завершится с ненулевым кодом.

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
  2. Извлекает текст и таблицы через pdfplumber
  3. Разбирает строки и таблицы регулярными выражениями
  4. Сохраняет Invoice + LineItems
  5. Обновляет статус: processing | processed | failed
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
│   │   └── invoices/     # Invoice, LineItem, Celery task
│   └── tests/
└── frontend/
    └── src/
        ├── app/          # Next.js App Router
        └── lib/          # API-клиент, управление токенами
```

# Конфигурация базы данных

Этот проект поддерживает как PostgreSQL, так и SQLite для разработки и продакшена.

## Конфигурация

### PostgreSQL (рекомендуется для продакшена)

Используйте переменную окружения `DATABASE_URL` для подключения к PostgreSQL:

```bash
# Базовое подключение
DATABASE_URL=postgresql://username:password@host:port/database_name

# Примеры:
DATABASE_URL=postgresql://postgres:password@localhost:5432/utility_parser
DATABASE_URL=postgresql://user:pass@db.example.com:5432/myapp

# С SSL
DATABASE_URL=postgresql+ssl://postgres:password@localhost:5432/utility_parser

# Альтернативная схема
DATABASE_URL=postgres://postgres:password@localhost:5432/utility_parser
```

### SQLite (по умолчанию для разработки)

Если `DATABASE_URL` не указан, автоматически используется SQLite:

```bash
# Не указывайте DATABASE_URL или установите пустое значение
unset DATABASE_URL
# или
DATABASE_URL=
```

## Поддерживаемые схемы

- `postgresql://` - стандартное подключение к PostgreSQL
- `postgresql+ssl://` - подключение с принудительным SSL
- `postgres://` - альтернативная схема для PostgreSQL

## Валидация

Конфигурация автоматически проверяет:
- Поддерживаемые схемы базы данных
- Наличие имени базы данных в URL
- Корректность формата URL

## Примеры использования

### Разработка (SQLite)
```bash
# .env файл
DEBUG=True
# DATABASE_URL не указан - используется SQLite
```

### Продакшен (PostgreSQL)
```bash
# .env файл
DEBUG=False
DATABASE_URL=postgresql://prod_user:secure_pass@prod-db.example.com:5432/utility_parser
```

### Продакшен с SSL
```bash
# .env файл
DEBUG=False
DATABASE_URL=postgresql+ssl://prod_user:secure_pass@prod-db.example.com:5432/utility_parser
```

## Миграции

После изменения конфигурации базы данных выполните миграции:

```bash
uv run python manage.py migrate
```

## Проверка конфигурации

Для проверки конфигурации базы данных:

```bash
uv run python manage.py check
uv run python manage.py showmigrations
``` 
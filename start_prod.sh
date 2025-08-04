#!/bin/bash

# Применяем миграции
echo "Applying database migrations..."
python manage.py migrate

# Собираем статические файлы
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Запускаем Granian
echo "Starting Granian server..."
granian --interface wsgi --host 0.0.0.0 --port 8000 utility_parser.wsgi:application 
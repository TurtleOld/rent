# Задание для агента: rent (учёт ЖКХ)

Этот файл — план работ для агента-исполнителя. Структурирован по фазам,
каждая фаза самодостаточна — можно остановиться между ними и проверить
систему в работе. Внутри фазы шаги выполнять по порядку.

## Контекст и инварианты

- **Стек**: Django 5 + DRF + SimpleJWT + Celery + Postgres 16 / Next.js 14 + TS / nginx.
- **Принцип «данные ровно из PDF»**: пользователь НЕ редактирует ни поля
  инвойса (поставщик, ЛС, ФИО, адрес, период, суммы), ни строки услуг.
  Если парсер ошибся — пользователь либо удаляет инвойс и перезагружает,
  либо жмёт «Перепарсить». Любое изменение значений = ошибка парсера.
- **Единицы**: «кв.м» и «куб.м» — РАЗНЫЕ величины (площадь vs объём),
  объединять их в одну категорию нельзя. Нормализация — только в пределах
  одной величины: `кв.м.` = `кв.м` = `м2` = `м²`; `куб.м.` = `куб.м` = `м3` = `м³`.
- **Деньги — Decimal на бэке**. JS `parseFloat` допустим только для
  отображения и графиков, никогда — для сохранения значений.
- **Никакого редактирования LineItem**. PDF — единственный источник истины.
- **Все изменения в одной транзакции** там, где меняется набор связанных
  объектов (Invoice + LineItem + Service-FK).
- **Тесты обязательны** для всех новых публичных функций бэка
  (валидация, парсинг, нормализация, сериализация, эндпоинты).
- **Совместимость миграций**: каждая миграция должна применяться чисто
  на пустую БД и на БД с существующими данными.

## Как работать с этим файлом

- Делать одну фазу целиком, потом переходить к следующей.
- В конце каждой фазы — запустить тесты бэка и `npm run build` фронта.
- Внутри фазы коммитить по логическим блокам (см. разделы внутри фаз).
- Все строки UI — на русском.

---

# PHASE 1 — Безопасность (критично)

Цель: закрыть критичные дыры и привести прод-настройки в порядок.
После этой фазы никакая утечка PDF, XSS-кража токена или брутфорс
логина не должны быть возможны при стандартных сценариях.

## 1.1. Закрыть прямой доступ к /media через X-Accel-Redirect

**Файлы**: `nginx/nginx.conf`, `backend/apps/invoices/views.py`,
`backend/apps/invoices/urls.py`, `backend/config/urls.py`.

Шаги:

1. В `nginx/nginx.conf` поменять блок `location /media/`:
   - Сделать его `internal;` (защищённым от прямого доступа).
   - Оставить `alias /app/media/;`.
2. Добавить новый публичный маршрут на бэкенде:
   `GET /api/invoices/<int:pk>/file/` →
   `InvoiceFileDownloadView` (новый, в `apps/invoices/views.py`).
3. View логика:
   - `permission_classes = [IsAuthenticated]`.
   - Получить инвойс через
     `get_object_or_404(Invoice, pk=pk, user=request.user)`.
   - Вернуть `HttpResponse` со статусом 200, заголовками:
     - `X-Accel-Redirect: /protected-media/<имя_файла_из_pdf_file.name>`
     - `Content-Type: application/pdf`
     - `Content-Disposition: inline; filename="invoice_<pk>.pdf"`
   - Тело — пустое (nginx подменит).
4. В nginx добавить `location /protected-media/`:
   ```
   internal;
   alias /app/media/;
   ```
   И `internal`-маршрут БЕЗ `expires`/`Cache-Control` (это персональные
   данные, кешировать нельзя).
5. Зарегистрировать URL в `apps/invoices/urls.py`.
6. Удалить из `backend/config/urls.py` блок `if settings.DEBUG: static(...)`,
   потому что:
   - В deve фронт работает через `next dev` + rewrites, файлы в /media
     там не нужны.
   - Никакого пути «фронт ходит за PDF напрямую» больше нет — только
     через `/api/invoices/<id>/file/`.
7. На фронте: добавить в `frontend/src/lib/api.ts`:
   ```ts
   export function invoiceFileUrl(id: number): string {
     return `/api/invoices/${id}/file/`;
   }
   ```
   И использовать в `frontend/src/app/invoices/[id]/page.tsx` для
   ссылки «Открыть PDF», если есть. Если ссылки нет — просто оставить
   функцию доступной.
8. Тест:
   - `tests/test_invoices.py`: добавить
     `test_file_download_requires_auth`,
     `test_file_download_forbidden_for_other_user`,
     `test_file_download_returns_x_accel_redirect_header`.

## 1.2. httpOnly access_token + Next.js прокси

**Файлы**: `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`,
`frontend/src/middleware.ts`,
`frontend/src/app/auth-cookie/set-refresh/route.ts`,
`frontend/src/app/auth-cookie/clear/route.ts`,
новые: `frontend/src/app/auth-cookie/set-access/route.ts`,
`frontend/src/app/api/[...path]/route.ts`.

Шаги:

1. Создать `frontend/src/app/auth-cookie/set-access/route.ts`:
   - POST принимает `{ access: string }`.
   - Ставит cookie `access_token` с `httpOnly: true`,
     `secure: process.env.NODE_ENV === "production"`, `sameSite: "lax"`,
     `path: "/"`, `maxAge: 60 * 60` (1 час, как в SimpleJWT).
2. Обновить `frontend/src/lib/auth.ts`:
   - `setTokens(access, refresh)` теперь дёргает оба route handler'а
     (`set-access` и `set-refresh`).
   - Убрать `document.cookie = "access_token=..."` (он больше не нужен,
     все cookies httpOnly).
   - `isAuthenticated()` теперь нельзя реализовать на клиенте; удалить
     эту функцию и любые её вызовы (заменить на просто рендер UI —
     middleware и так делает редирект).
   - `clearTokens()` остаётся, бьёт `/auth-cookie/clear`.
3. Создать catch-all прокси `frontend/src/app/api/[...path]/route.ts`:
   - Экспортирует `GET`, `POST`, `PATCH`, `DELETE`, `PUT`.
   - Каждая функция:
     - Читает cookie `access_token` через `request.cookies.get(...)`.
     - Берёт `path` из `params.path`, строит
       `${process.env.BACKEND_URL ?? "http://backend:8000"}/api/${path.join('/')}${search}`.
     - Проксирует тело, метод, заголовки (исключая `host`, `cookie`),
       подмешивая `Authorization: Bearer ${access_token}`, если cookie есть.
     - Для `multipart/form-data` (загрузка PDF) — прокидывать тело как
       `Readable` без буферизации (используется
       `request.body` + `duplex: "half"` в `fetch`).
     - Возвращает ответ бэка как есть.
   - Если бэк ответил 401 — стереть httpOnly cookies в ответе и вернуть 401.
4. Обновить `frontend/src/lib/api.ts`:
   - `getAccessToken()` и `authHeaders()` — удалить.
   - `request()` больше не добавляет `Authorization`. Cookies идут
     автоматически (`credentials: "include"` оставить).
   - `uploadInvoice()` — убрать вычисление `authHeaders()`.
5. Обновить `frontend/src/middleware.ts`:
   - Логика остаётся (cookie `access_token` → авторизован), но cookie
     теперь httpOnly — Next-middleware всё равно её видит. Проверить.
6. Добавить env-переменную `BACKEND_URL` в `docker-compose.yml`
   для `frontend`: `BACKEND_URL=http://backend:8000`.
7. Удалить из `next.config.mjs` блок rewrites — прокси теперь делает
   route handler. В dev запускать backend + frontend локально, ходить
   через `/api/...`.
8. Проверить, что весь рабочий поток (login → dashboard → upload →
   detail → payment → logout) проходит через прокси.

## 1.3. Secure-настройки Django

**Файл**: `backend/config/settings.py`.

Добавить в конец файла блок:

```python
# Production hardening (no-op при DEBUG=True)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
```

В `nginx/nginx.conf` — добавить заголовок
`X-Forwarded-Proto $scheme;` в проксирование `/api/`, `/admin/`
(уже есть, проверить).

## 1.4. JWT blacklist и реальный logout

**Файлы**: `backend/config/settings.py`, `backend/apps/accounts/urls.py`,
`backend/apps/accounts/views.py`,
новый — `frontend/src/app/api/auth/logout/route.ts` или прямой вызов
существующего `clearTokens()`.

Шаги:

1. Добавить в `INSTALLED_APPS`: `"rest_framework_simplejwt.token_blacklist"`.
2. В `SIMPLE_JWT` поменять `BLACKLIST_AFTER_ROTATION` → `True`.
3. Применить миграцию (агент: проверить, что `python manage.py migrate`
   проходит).
4. Добавить эндпоинт `POST /api/auth/logout/`:
   - View, наследующий `TokenBlacklistView` из simplejwt.
   - Принимает `{ "refresh": "<token>" }` и блеклистит его.
5. На фронте: в `clearTokens()` сначала POST `/api/auth/logout/`
   с refresh-токеном (взять из httpOnly cookie через серверный
   helper — добавить route handler `/auth-cookie/logout` который
   читает refresh_token cookie, дёргает Django, потом удаляет cookies).
6. Тесты:
   `tests/test_accounts.py`: `test_logout_blacklists_refresh_token`.

## 1.5. Magic-bytes валидация PDF + лимиты celery

**Файлы**: `backend/apps/invoices/serializers.py`,
`backend/apps/invoices/tasks.py`.

Шаги:

1. В `InvoiceUploadSerializer.validate_pdf_file`:
   ```python
   header = value.read(5)
   value.seek(0)
   if header != b"%PDF-":
       raise serializers.ValidationError(
           "Файл не является валидным PDF (отсутствует сигнатура %PDF-)."
       )
   ```
2. В `@shared_task` на `process_invoice` добавить аргументы:
   ```python
   soft_time_limit=60,
   time_limit=120,
   ```
3. В `_do_process` — обернуть `pdfplumber.open(...)` в try/except
   на `SoftTimeLimitExceeded`, чтобы пометить инвойс как FAILED
   с сообщением «PDF слишком большой или повреждён».
4. Лимит страниц: после `pdfplumber.open` проверить `len(pdf.pages)`,
   если > 50 — пометить FAILED с warning, не парсить.
5. Тесты:
   `tests/test_invoices.py`:
   `test_upload_rejects_non_pdf_by_magic_bytes`
   (отправить `.pdf` с произвольным содержимым).

## 1.6. Rate limiting логина и регистрации

**Файлы**: `backend/requirements.txt`, `backend/config/settings.py`,
`backend/apps/accounts/views.py`.

Шаги:

1. Добавить в `requirements.txt`:
   ```
   django-ratelimit==4.1.0
   ```
2. В `LoginView` и `RegisterView` навесить:
   ```python
   from django_ratelimit.decorators import ratelimit
   from django.utils.decorators import method_decorator

   @method_decorator(ratelimit(key="ip", rate="5/m", block=True), name="post")
   class LoginView(...): ...

   @method_decorator(ratelimit(key="ip", rate="3/h", block=True), name="post")
   class RegisterView(...): ...
   ```
3. Тесты: `tests/test_accounts.py` —
   `test_login_rate_limited_after_5_attempts`.

## 1.7. Убрать дефолтные пароли postgres из compose

**Файл**: `docker-compose.yml`.

Шаги:

1. Заменить `environment` postgres на `env_file: .env` (тот же, что
   у backend) и читать переменные `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_DB`.
2. Обновить `.env.example` (создать если нет) с дефолтами:
   ```
   POSTGRES_USER=rent
   POSTGRES_PASSWORD=changeme_in_prod
   POSTGRES_DB=rent
   ```
3. В `README.md` добавить пункт «обязательно сгенерировать пароль БД».

## 1.8. transaction.atomic вокруг _do_process

**Файл**: `backend/apps/invoices/tasks.py`.

```python
from django.db import transaction

def _do_process(invoice: Invoice) -> None:
    ...
    with transaction.atomic():
        invoice.save()
        LineItem.objects.filter(invoice=invoice).delete()
        LineItem.objects.bulk_create(line_items)
```

Тест:
`tests/test_invoices.py`: `test_reparse_does_not_leave_partial_state` —
имитировать падение между delete и create через mock, убедиться, что
старые LineItem остались.

## 1.9. Чек-лист фазы 1

- [ ] `docker compose down -v && docker compose up --build` проходит.
- [ ] Прямой `GET http://localhost/media/invoices/...pdf` → 404 / 403.
- [ ] `GET /api/invoices/<id>/file/` под своим пользователем → отдаёт PDF.
- [ ] `GET /api/invoices/<id>/file/` под чужим пользователем → 404.
- [ ] `document.cookie` в браузере не содержит `access_token`.
- [ ] Логин/логаут работают, после logout refresh-токен невалиден
  (получить 401 на refresh).
- [ ] 6-й логин подряд за минуту с одного IP → 429.
- [ ] Загрузка фейкового `.pdf` (текстовый файл, переименованный) → 400.
- [ ] `python manage.py test tests` — все тесты зелёные.
- [ ] `npm run build` во frontend — без ошибок.

---

# PHASE 2 — Модели Service / алиасы / нормализация единиц

Цель: ввести нормализованный справочник услуг и единиц измерения,
автоматически связать существующие LineItem со Service, дать
бэкенд-эндпоинт для истории тарифа по услуге.

## 2.1. Каталог канонических единиц

**Файл**: новый `backend/apps/invoices/units.py`.

Содержание:

```python
"""Канонические единицы измерения и их алиасы."""

# Канонические формы — то, что сохраняется в БД и показывается в UI.
# value -> (квадратные метры, куб метры, штуки...). Это РАЗНЫЕ величины,
# нельзя сводить «кв.м» и «куб.м» к одному.
CANONICAL_UNITS = {
    "кв.м",       # площадь
    "куб.м",      # объём (вода, газ)
    "кВт·ч",      # электроэнергия
    "Гкал",       # тепло
    "чел",        # человек
    "шт",         # штуки
}

# Маппинг (после .strip().lower() и удаления конечной точки) -> канон.
UNIT_ALIASES = {
    # площадь
    "кв.м": "кв.м", "кв.м.": "кв.м", "м2": "кв.м", "м²": "кв.м",
    "кв м": "кв.м", "квм": "кв.м",
    # объём
    "куб.м": "куб.м", "куб.м.": "куб.м", "м3": "куб.м", "м³": "куб.м",
    "куб м": "куб.м", "кубм": "куб.м",
    # электро
    "квт·ч": "кВт·ч", "квт.ч": "кВт·ч", "квтч": "кВт·ч",
    "квт ч": "кВт·ч", "kwh": "кВт·ч",
    # тепло
    "гкал": "Гкал",
    # люди / штуки
    "чел": "чел", "чел.": "чел", "человек": "чел",
    "шт": "шт", "шт.": "шт", "штука": "шт",
}


def normalize_unit(raw: str | None) -> str | None:
    """Приводит запись единицы из PDF к канонической форме.

    Не объединяет разные величины (площадь vs объём).
    Возвращает None, если строка не распознана — в этом случае
    оставляем исходное значение (для warning) и не трогаем графики.
    """
    if not raw:
        return None
    key = raw.strip().lower().rstrip(".")
    if key in UNIT_ALIASES:
        return UNIT_ALIASES[key]
    return None
```

Тесты `tests/test_units.py` (новый файл):

- `normalize_unit("кв.м.") == "кв.м"`
- `normalize_unit("м²") == "кв.м"`
- `normalize_unit("куб.м.") == "куб.м"`
- `normalize_unit("м³") == "куб.м"`
- `normalize_unit("кв.м") != normalize_unit("куб.м")` (важно!)
- `normalize_unit("какая-то фигня") is None`
- `normalize_unit(None) is None`

## 2.2. Модели Service и ServiceAlias

**Файл**: `backend/apps/invoices/models.py`.

Добавить:

```python
class Service(models.Model):
    """Канонический справочник услуг ЖКХ.

    Уникален в рамках пары (user, canonical_name) — у каждого
    пользователя свой каталог, потому что состав услуг и поставщики
    различаются.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="services",
    )
    canonical_name = models.CharField(max_length=255)
    unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Каноническая единица измерения (кв.м, куб.м, кВт·ч...)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "canonical_name"],
                name="uniq_user_service_canonical",
            ),
        ]
        ordering = ["canonical_name"]

    def __str__(self) -> str:
        return f"{self.canonical_name} ({self.user_id})"


class ServiceAlias(models.Model):
    """Связывает разные написания названия услуги из PDF с одной Service.

    Пример: «ХОЛОДНОЕ В/С», «ХОЛОДНОЕ ВОДОСНАБЖЕНИЕ», «ХВС» -> Service «ХВС».
    """
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    raw_name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "raw_name"],
                name="uniq_service_alias_raw",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.raw_name} -> {self.service.canonical_name}"
```

И к `LineItem` добавить:

```python
service = models.ForeignKey(
    "invoices.Service",
    on_delete=models.SET_NULL,
    blank=True,
    null=True,
    related_name="line_items",
)
```

Создать миграцию `0005_service_servicealias_lineitem_service.py`
через `python manage.py makemigrations invoices`.

## 2.3. Data-миграция: автосоздание Service из существующих LineItem

**Файл**: новая миграция `0006_populate_services.py`.

```python
from django.db import migrations


def normalize_for_match(name: str) -> str:
    """Стандартизация для сравнения имён (uppercase + схлоп пробелов)."""
    return " ".join(name.strip().upper().split())


def populate_services(apps, schema_editor):
    Invoice = apps.get_model("invoices", "Invoice")
    LineItem = apps.get_model("invoices", "LineItem")
    Service = apps.get_model("invoices", "Service")
    ServiceAlias = apps.get_model("invoices", "ServiceAlias")

    # Per-user map: normalized_name -> Service.id
    user_services: dict[tuple[int, str], int] = {}

    for li in LineItem.objects.select_related("invoice").iterator():
        user_id = li.invoice.user_id
        raw = (li.service_name or "").strip()
        if not raw:
            continue
        norm = normalize_for_match(raw)
        key = (user_id, norm)

        if key not in user_services:
            # Используем первое встретившееся написание как canonical.
            svc = Service.objects.create(
                user_id=user_id,
                canonical_name=raw,
                unit=li.unit,  # перезапишется позже из normalize_unit
            )
            user_services[key] = svc.id

        svc_id = user_services[key]
        if li.service_id != svc_id:
            li.service_id = svc_id
            li.save(update_fields=["service"])

        # Заводим alias на каждое уникальное raw-написание.
        ServiceAlias.objects.get_or_create(
            service_id=svc_id,
            raw_name=raw,
        )


def reverse_noop(apps, schema_editor):
    # Откат не пытается убирать данные — это безопасно.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("invoices", "0005_service_servicealias_lineitem_service"),
    ]
    operations = [
        migrations.RunPython(populate_services, reverse_noop),
    ]
```

После миграции — в админке через UI пользователь сможет объединить
дубли (см. шаг 2.6).

## 2.4. Обновить парсер: автоматическая привязка к Service

**Файл**: `backend/apps/invoices/tasks.py`.

Шаги:

1. После создания `LineItem` пройтись по ним и:
   - Нормализовать `unit` через `normalize_unit()` — если есть канон,
     сохранить его, иначе оставить сырое значение + добавить warning
     в `invoice.warnings`.
   - Найти/создать `Service` для текущего user:
     - Найти `ServiceAlias` с `raw_name=li.service_name` среди алиасов
       сервисов этого user.
     - Если есть — взять связанный Service, проставить `li.service`.
     - Если нет — создать Service с
       `canonical_name=li.service_name, unit=normalized_unit`
       и `ServiceAlias(service=..., raw_name=li.service_name)`.
2. Всё это — внутри той же `transaction.atomic` из 1.8.
3. Тесты `tests/test_invoices.py`:
   - `test_parsing_creates_service_for_new_name`
   - `test_parsing_reuses_existing_service_via_alias`
   - `test_parsing_normalizes_units`

## 2.5. API: список сервисов и история тарифов

**Файл**: `backend/apps/invoices/views.py`,
`backend/apps/invoices/urls.py`,
`backend/apps/invoices/serializers.py`.

Новые view:

```python
class ServiceListView(generics.ListAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Service.objects
            .filter(user=self.request.user)
            .prefetch_related("aliases")
            .order_by("canonical_name")
        )


class ServiceTariffHistoryView(views.APIView):
    """История тарифа и потребления по услуге.

    GET /api/services/<id>/history/
    Возвращает JSON:
    {
      "service": {"id": ..., "canonical_name": ..., "unit": ...},
      "points": [
        {"period": "2026-01", "tariff": "40.7300", "quantity": "12.5",
         "amount_charged": "509.13", "amount": "509.13",
         "change_pct": null},
        {"period": "2026-02", "tariff": "42.5000", ...,
         "change_pct": 4.34},  # рост тарифа от предыдущего периода
      ]
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        service = get_object_or_404(Service, pk=pk, user=request.user)
        rows = (
            LineItem.objects
            .filter(service=service, invoice__user=request.user)
            .exclude(invoice__period_month__isnull=True)
            .select_related("invoice")
            .order_by("invoice__period_year", "invoice__period_month")
        )
        points = []
        prev_tariff = None
        for li in rows:
            inv = li.invoice
            period = f"{inv.period_year}-{inv.period_month:02d}"
            tariff = li.tariff
            change_pct = None
            if prev_tariff is not None and tariff is not None and prev_tariff > 0:
                change_pct = float((tariff - prev_tariff) / prev_tariff * 100)
            points.append({
                "period": period,
                "tariff": str(tariff) if tariff is not None else None,
                "quantity": str(li.quantity) if li.quantity is not None else None,
                "amount_charged": str(li.amount_charged) if li.amount_charged is not None else None,
                "amount": str(li.amount) if li.amount is not None else None,
                "change_pct": change_pct,
            })
            if tariff is not None:
                prev_tariff = tariff
        return Response({
            "service": ServiceSerializer(service).data,
            "points": points,
        })
```

Сериализатор:

```python
class ServiceAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceAlias
        fields = ("id", "raw_name")


class ServiceSerializer(serializers.ModelSerializer):
    aliases = ServiceAliasSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = ("id", "canonical_name", "unit", "aliases",
                  "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at", "aliases")
```

URL:

- `GET /api/services/` → список
- `GET /api/services/<int:pk>/history/` → история тарифа

Тесты:

- `tests/test_services.py` (новый):
  - `test_service_list_returns_only_users_services`
  - `test_history_returns_sorted_points`
  - `test_history_computes_change_pct`
  - `test_history_skips_invoices_without_period`

## 2.6. Админка для слияния дублей

**Файл**: `backend/apps/invoices/admin.py`.

Добавить:

```python
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("id", "canonical_name", "user", "unit", "aliases_count")
    list_filter = ("user",)
    search_fields = ("canonical_name", "aliases__raw_name")
    actions = ["merge_into_first"]

    def aliases_count(self, obj):
        return obj.aliases.count()
    aliases_count.short_description = "Алиасов"

    @admin.action(description="Объединить выбранные в первую запись")
    def merge_into_first(self, request, queryset):
        services = list(queryset.order_by("id"))
        if len(services) < 2:
            self.message_user(request, "Нужно выбрать минимум 2 сервиса.")
            return
        target = services[0]
        from .models import LineItem, ServiceAlias
        for src in services[1:]:
            if src.user_id != target.user_id:
                self.message_user(
                    request,
                    f"Пропущен Service #{src.id} — другой пользователь.",
                )
                continue
            LineItem.objects.filter(service=src).update(service=target)
            ServiceAlias.objects.filter(service=src).update(service=target)
            src.delete()
        self.message_user(request, f"Объединено в Service #{target.id}.")
```

## 2.7. Чек-лист фазы 2

- [ ] `python manage.py migrate` чисто на пустой БД.
- [ ] `python manage.py migrate` чисто на БД с данными от PHASE 1.
- [ ] У каждого существующего LineItem проставлен `service_id`.
- [ ] У каждого Service есть хотя бы один ServiceAlias.
- [ ] `GET /api/services/` возвращает только свои сервисы.
- [ ] `GET /api/services/<id>/history/` возвращает точки в правильном порядке.
- [ ] `normalize_unit` различает кв.м и куб.м.
- [ ] В админке action «Объединить» работает.
- [ ] Все тесты зелёные, `npm run build` ок.

---

# PHASE 3 — Валидация консистентности + warnings

Цель: при сохранении инвойса автоматически проверять арифметику и
писать расхождения в `Invoice.warnings`. Ничего не блокирует
(данные сохраняются как есть из PDF).

## 3.1. Валидатор

**Файл**: новый `backend/apps/invoices/validators.py`.

```python
"""Валидаторы консистентности инвойса.

Все проверки — soft: возвращают список текстовых warning'ов,
ничего не блокируют. PDF может содержать ошибки поставщика —
наша задача показать их пользователю, а не исправлять.
"""
from decimal import Decimal
from typing import Iterable

from .models import Invoice, LineItem

# Толеранс — копеечные расхождения округления.
TOLERANCE = Decimal("0.02")


def _close(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return True  # нечего сравнивать
    return abs(a - b) <= TOLERANCE


def check_line_item(li: LineItem) -> list[str]:
    """quantity * tariff ≈ amount_charged
    amount_charged + (recalculation or 0) + (debt or 0) ≈ amount"""
    warnings: list[str] = []

    if li.quantity is not None and li.tariff is not None and li.amount_charged is not None:
        expected = (li.quantity * li.tariff).quantize(Decimal("0.01"))
        if not _close(expected, li.amount_charged):
            warnings.append(
                f"«{li.service_name}»: количество × тариф "
                f"({expected}) ≠ начислено ({li.amount_charged})."
            )

    if li.amount_charged is not None and li.amount is not None:
        rec = li.recalculation or Decimal("0")
        debt = li.debt or Decimal("0")
        expected_total = (li.amount_charged + rec + debt).quantize(Decimal("0.01"))
        if not _close(expected_total, li.amount):
            warnings.append(
                f"«{li.service_name}»: начислено + перерасчёт + долг "
                f"({expected_total}) ≠ итого ({li.amount})."
            )

    return warnings


def check_invoice_totals(invoice: Invoice, line_items: Iterable[LineItem]) -> list[str]:
    """Σ line_items.amount ≈ amount_due (или amount_due_without_insurance)."""
    warnings: list[str] = []
    total = sum((li.amount or Decimal("0") for li in line_items), Decimal("0"))

    reference = invoice.amount_due_without_insurance or invoice.amount_due
    if reference is not None and not _close(total, reference):
        warnings.append(
            f"Сумма по строкам ({total}) ≠ итог квитанции ({reference})."
        )
    return warnings


def run_all_checks(invoice: Invoice, line_items: Iterable[LineItem]) -> list[str]:
    out: list[str] = []
    for li in line_items:
        out.extend(check_line_item(li))
    out.extend(check_invoice_totals(invoice, line_items))
    return out
```

## 3.2. Интеграция в celery-таску

**Файл**: `backend/apps/invoices/tasks.py`.

В `_do_process` после bulk_create:

```python
from .validators import run_all_checks
...
extra_warnings = run_all_checks(invoice, line_items)
if extra_warnings:
    invoice.warnings = (invoice.warnings or []) + extra_warnings
    invoice.save(update_fields=["warnings", "updated_at"])
```

## 3.3. Тесты

`tests/test_validators.py` (новый):

- `test_quantity_times_tariff_ok_no_warning`
- `test_quantity_times_tariff_off_emits_warning`
- `test_amount_charged_plus_recalc_plus_debt_equals_amount`
- `test_totals_mismatch_emits_warning`
- `test_none_values_dont_explode`
- `test_tolerance_002_passes`

## 3.4. Чек-лист фазы 3

- [ ] Тесты валидаторов зелёные.
- [ ] Загрузка PDF с искусственным расхождением → warning виден
  в UI на странице инвойса.
- [ ] Загрузка корректного PDF → новых warning'ов не появляется.

---

# PHASE 4 — Убрать редактирование Invoice, добавить «Перепарсить»

Цель: сделать UI и API соответствующими принципу «данные ровно из PDF».

## 4.1. Бэкенд: read-only Invoice

**Файлы**: `backend/apps/invoices/views.py`,
`backend/apps/invoices/serializers.py`.

Шаги:

1. В `InvoiceDetailView` оставить `http_method_names = ["get", "delete", "head", "options"]`.
2. В `InvoiceSerializer.Meta.read_only_fields` добавить ВСЕ поля
   (по сути сериализатор становится полностью read-only):
   ```python
   read_only_fields = tuple(
       f for f in InvoiceSerializer.Meta.fields if f != "id"
   ) + ("id",)
   ```
   Или просто перечислить все.
3. Тест: `tests/test_invoices.py` —
   `test_patch_invoice_returns_405`.

## 4.2. Эндпоинт «Перепарсить»

**Файлы**: `backend/apps/invoices/views.py`,
`backend/apps/invoices/urls.py`.

```python
class InvoiceReparseView(views.APIView):
    """POST /api/invoices/<id>/reparse/ — повторно запустить парсинг.

    Сбрасывает статус инвойса в PROCESSING, очищает warning'и и
    запускает celery-таску. line_items будут пересозданы в задаче.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        if invoice.status == Invoice.Status.PROCESSING:
            return Response(
                {"detail": "Инвойс уже обрабатывается."},
                status=status.HTTP_409_CONFLICT,
            )
        invoice.status = Invoice.Status.PROCESSING
        invoice.error_message = None
        invoice.warnings = []
        invoice.save(update_fields=[
            "status", "error_message", "warnings", "updated_at",
        ])
        process_invoice.delay(invoice.pk)
        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_202_ACCEPTED,
        )
```

URL: `POST /api/invoices/<int:pk>/reparse/`.

Тест:
`test_reparse_resets_status_and_dispatches_task`,
`test_reparse_returns_409_if_already_processing`.

## 4.3. Фронт: убрать редактирование

**Файл**: `frontend/src/app/invoices/[id]/page.tsx`.

Шаги:

1. Удалить:
   - `editing`, `setEditing`
   - `editData`, `setEditData`
   - `handleSaveEdit`
   - блок `{editing ? ... : ...}` — оставить только ветку отображения.
   - константы `EDITABLE_LABELS`, тип `EditableFields`.
2. Удалить `editBtn` и `saveBtn`/`cancelBtn` в этом файле.
3. Добавить кнопку «Перепарсить PDF» рядом с «Удалить»:
   - Видна, если `invoice.status === "processed"` или `"failed"`.
   - Дёргает `POST /api/invoices/<id>/reparse/` → перезагружает страницу
     и запускает поллинг (как сейчас при status=processing).
4. Удалить из `frontend/src/lib/api.ts` функцию `patchInvoice`.
5. Добавить:
   ```ts
   export async function reparseInvoice(id: number): Promise<Invoice> {
     return request<Invoice>(`/invoices/${id}/reparse/`, {
       method: "POST",
     });
   }
   ```

## 4.4. Чек-лист фазы 4

- [ ] В UI инвойса нет кнопки «Редактировать».
- [ ] Есть кнопка «Перепарсить PDF», она работает.
- [ ] `PATCH /api/invoices/<id>/` → 405.
- [ ] Тесты зелёные.

---

# PHASE 5 — Чистка: декомпозиция, исправление N+1, 401-handler

Цель: техдолг, не блокирующий новый функционал, но облегчающий
дальнейшую работу.

## 5.1. annotate(total_paid) и payment_status в SQL

**Файл**: `backend/apps/invoices/views.py`,
`backend/apps/invoices/models.py`,
`backend/apps/invoices/serializers.py`.

Шаги:

1. В `InvoiceListView.get_queryset` и `InvoiceDetailView.get_queryset`:
   ```python
   from django.db.models import Sum, F, DecimalField, Case, When, Value
   from django.db.models.functions import Coalesce

   qs = (
       Invoice.objects.filter(user=self.request.user)
       .prefetch_related("line_items")
       .annotate(
           _total_paid=Coalesce(
               Sum("payments__amount"),
               Value(Decimal("0")),
               output_field=DecimalField(max_digits=12, decimal_places=2),
           ),
       )
   )
   ```
2. В `Invoice` — добавить `total_paid` как метод, который сначала
   читает `_total_paid`, если он есть, иначе фолбэк на python-sum.
3. `payment_status` тоже использует `total_paid`.
4. Сериализатор оставить как есть — `ReadOnlyField` сработает через
   property.

Тест:
`tests/test_invoices.py` —
`test_invoice_list_does_not_query_payments_per_invoice` (использовать
`assertNumQueries`).

## 5.2. 401-handler в API-клиенте

**Файл**: `frontend/src/lib/api.ts`.

В `request()` после `if (!res.ok)`:

```ts
if (res.status === 401) {
  // httpOnly cookie — чистит сам route handler логаута.
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}
```

## 5.3. Декомпозиция reports/page.tsx

**Файлы**: новые
`frontend/src/components/LineChart.tsx`,
`frontend/src/components/ServiceChart.tsx`,
`frontend/src/lib/reports.ts`.

Шаги:

1. Вынести `LineChart` и `ServiceChart` в отдельные файлы.
2. Вынести `periodLabel`, `periodKey`, `VOLUME_UNITS_EXCLUDE`,
   `showVolume` в `lib/reports.ts`.
3. `reports/page.tsx` остаётся только страничной логикой и
   `useMemo`-агрегациями.
4. Заменить `VOLUME_UNITS_EXCLUDE` логикой через canonical unit:
   показывать график объёма только если `unit === "куб.м"` или
   `"кВт·ч"` или `"Гкал"` (если `service.unit` есть).

## 5.4. Раздел «История тарифов» в /reports

**Файл**: `frontend/src/app/reports/page.tsx`.

Шаги:

1. Добавить новую секцию «Динамика тарифов» — таблица:
   - колонки: Услуга, Единица, Тариф (текущий), Изменение от предыдущего месяца (%).
   - данные тянутся параллельно из `/api/services/` и
     `/api/services/<id>/history/` (батчем — для всех сервисов сразу,
     это N запросов; OK для MVP, оптимизация — позже).
2. Сортировка по % роста по убыванию — самые «подорожавшие» сверху.
3. Подсветка строк: рост >10% — красный фон, рост >25% — насыщенно-красный.

Тесты — только smoke на бэк (фаза 2 их уже покрыла).

## 5.5. Чек-лист фазы 5

- [ ] `assertNumQueries` на список инвойсов — фиксированное число.
- [ ] Истёкший токен → редирект на /login.
- [ ] reports/page.tsx меньше 200 строк.
- [ ] Раздел «Динамика тарифов» отображается и подсвечивает рост.

---

# Карта файлов (для быстрой ориентации)

## Новые файлы

- `backend/apps/invoices/units.py` — нормализация единиц измерения.
- `backend/apps/invoices/validators.py` — soft-валидация консистентности.
- `backend/tests/test_units.py`
- `backend/tests/test_validators.py`
- `backend/tests/test_services.py`
- `frontend/src/app/api/[...path]/route.ts` — прокси-обёртка над Django.
- `frontend/src/app/auth-cookie/set-access/route.ts`
- `frontend/src/app/auth-cookie/logout/route.ts`
- `frontend/src/components/LineChart.tsx`
- `frontend/src/components/ServiceChart.tsx`
- `frontend/src/lib/reports.ts`
- `TASKS.md` (этот файл).

## Меняющиеся файлы

- `nginx/nginx.conf` — `internal` на /media, новый `/protected-media`.
- `docker-compose.yml` — env_file для postgres, `BACKEND_URL` для frontend.
- `backend/config/settings.py` — SECURE_*, blacklist.
- `backend/config/urls.py` — убрать static() в DEBUG-блоке.
- `backend/apps/invoices/models.py` — Service, ServiceAlias, FK на LineItem.
- `backend/apps/invoices/views.py` — реструктуризация (см. фазы).
- `backend/apps/invoices/serializers.py` — read-only Invoice, новые сериализаторы.
- `backend/apps/invoices/urls.py` — новые маршруты.
- `backend/apps/invoices/tasks.py` — atomic, normalize_unit, service mapping, validators.
- `backend/apps/invoices/admin.py` — Service admin с merge-action.
- `backend/apps/accounts/views.py` — rate limit, logout.
- `backend/apps/accounts/urls.py` — logout.
- `backend/requirements.txt` — django-ratelimit.
- `frontend/src/lib/api.ts` — убрать patchInvoice, добавить reparse и
  invoiceFileUrl, 401-handler.
- `frontend/src/lib/auth.ts` — httpOnly cookies.
- `frontend/src/middleware.ts` — без изменений по логике.
- `frontend/src/app/invoices/[id]/page.tsx` — убрать форму редактирования,
  кнопка «Перепарсить».
- `frontend/src/app/reports/page.tsx` — декомпозиция + «Динамика тарифов».
- `frontend/src/app/auth-cookie/set-refresh/route.ts` —
  не меняется по логике, проверить флаги.
- `next.config.mjs` — убрать dev-rewrite (его заменяет прокси).
- `README.md` — обновить раздел про переменные окружения и про БД.

## Удаляемые файлы

- Нет.

---

# Глобальные правила выполнения

1. **Один коммит — одна логическая единица.** Не смешивать «миграция»
   и «вью» в одном коммите.
2. **Не отключать тесты**, чтобы пройти CI. Если тест падает — чинить
   код, а не тест.
3. **Не использовать `--no-verify`** на git commit.
4. **После каждой фазы** — прогнать чек-лист фазы и зафиксировать.
5. **Если встречается неоднозначность** в этом плане — остановиться и
   спросить пользователя, а не выбирать самостоятельно.
6. **Сообщения коммитов** в стиле существующих:
   `feat(invoices): ...`, `fix(security): ...`, `refactor(reports): ...`.

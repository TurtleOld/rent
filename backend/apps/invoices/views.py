import logging

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, parsers, permissions, status, views
from rest_framework.response import Response

from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceUploadSerializer, ManualAmountDueSerializer
from .tasks import STUCK_AFTER, process_invoice

logger = logging.getLogger(__name__)

# Без внутренних адресов и причин сбоя брокера: их место в логах, не в ответе.
QUEUE_UNAVAILABLE_MESSAGE = (
    "Очередь обработки временно недоступна. "
    "Квитанция и её данные сохранены, повторите разбор позже."
)


def _invoice_queryset(user):
    return (
        Invoice.objects.filter(user=user)
        .prefetch_related("line_items")
        .order_by("-created_at")
    )


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return _invoice_queryset(self.request.user)


class InvoiceUploadView(generics.CreateAPIView):
    serializer_class = InvoiceUploadSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        invoice = serializer.instance
        try:
            process_invoice.delay(invoice.pk)
        except Exception:
            logger.exception("Не удалось поставить задачу разбора квитанции %s", invoice.pk)
            # update, а не save: не воскрешаем квитанцию, удалённую во время запроса.
            Invoice.objects.filter(pk=invoice.pk).update(
                status=Invoice.Status.FAILED,
                error_message=QUEUE_UNAVAILABLE_MESSAGE,
                updated_at=timezone.now(),
            )
            return Response(
                {"detail": QUEUE_UNAVAILABLE_MESSAGE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )


class InvoiceDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return _invoice_queryset(self.request.user)


class InvoiceFileDownloadView(views.APIView):
    """Serves an invoice PDF via X-Accel-Redirect (nginx internal redirect).

    Only the authenticated owner of the invoice can download it.
    The response body is empty; nginx replaces it with the actual file.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        response = HttpResponse(status=200, content_type="application/pdf")
        response["X-Accel-Redirect"] = f"/protected-media/{invoice.pdf_file.name}"
        response["Content-Disposition"] = f'inline; filename="invoice_{pk}.pdf"'
        return response


class InvoiceReparseView(views.APIView):
    """Переводит квитанцию в «Обрабатывается» и снова ставит задачу разбора.

    Доступно в статусах «Обработан», «Обработан частично» и «Ошибка», а также
    когда обработка зависла (воркер умер посреди задачи) дольше STUCK_AFTER.
    Сбой постановки задачи возвращает квитанцию в «Ошибка» с понятным
    сообщением, не трогая PDF и распознанные данные.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int) -> Response:
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        if (
            invoice.status == Invoice.Status.PROCESSING
            and invoice.updated_at > timezone.now() - STUCK_AFTER
        ):
            return Response(
                {"detail": "Квитанция уже обрабатывается."},
                status=status.HTTP_409_CONFLICT,
            )
        previous_warnings = invoice.warnings
        invoice.status = Invoice.Status.PROCESSING
        invoice.error_message = None
        invoice.warnings = []
        invoice.save(update_fields=["status", "error_message", "warnings", "updated_at"])
        try:
            process_invoice.delay(invoice.pk)
        except Exception:
            logger.exception("Не удалось поставить задачу разбора квитанции %s", invoice.pk)
            # update, а не save: не воскрешаем квитанцию, удалённую во время запроса.
            Invoice.objects.filter(pk=invoice.pk).update(
                status=Invoice.Status.FAILED,
                error_message=QUEUE_UNAVAILABLE_MESSAGE,
                warnings=previous_warnings,
                updated_at=timezone.now(),
            )
            return Response(
                {"detail": QUEUE_UNAVAILABLE_MESSAGE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            InvoiceSerializer(invoice).data,
            status=status.HTTP_202_ACCEPTED,
        )


class InvoiceManualAmountDueView(views.APIView):
    """Задаёт или сбрасывает ручную сумму к оплате квитанции.

    Доступно только владельцу и только для квитанции в статусе «Обработан».
    Пустое значение сбрасывает ручную сумму, и снова действует распознанная.
    """

    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, pk: int) -> Response:
        invoice = get_object_or_404(Invoice, pk=pk, user=request.user)
        serializer = ManualAmountDueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Статус проверяется в самом UPDATE: повторный разбор, начатый после чтения
        # квитанции, иначе сохранил бы её целиком и затёр введённую сумму.
        updated = Invoice.objects.filter(pk=invoice.pk, status=Invoice.Status.PROCESSED).update(
            manual_amount_due=serializer.validated_data["manual_amount_due"],
            updated_at=timezone.now(),
        )
        if not updated:
            return Response(
                {"detail": "Сумму к оплате можно ввести только для обработанной квитанции."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(InvoiceSerializer(_invoice_queryset(request.user).get(pk=pk)).data)

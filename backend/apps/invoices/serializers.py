from rest_framework import serializers

from .models import AMOUNT_DUE_UNKNOWN_WARNING, Invoice, LineItem


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = "__all__"
        read_only_fields = ("invoice",)


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)
    payment_status = serializers.ReadOnlyField()
    total_paid = serializers.ReadOnlyField()
    amount_due = serializers.DecimalField(
        source="effective_amount_due", max_digits=10, decimal_places=2, read_only=True
    )
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "pdf_file",
            "status",
            "error_message",
            "provider_name",
            "account_number",
            "payer_name",
            "address",
            "period_start",
            "period_end",
            "period_month",
            "period_year",
            "amount_due",
            "manual_amount_due",
            "amount_due_without_insurance",
            "amount_due_with_insurance",
            "amount_charged",
            "amount_paid_ai",
            "amount_recalculation",
            "confidence",
            "warnings",
            "payment_status",
            "total_paid",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_warnings(self, invoice: Invoice) -> list[str]:
        # Ручная сумма закрывает проблему нераспознанной суммы, пока её не сбросят.
        if invoice.manual_amount_due is None:
            return invoice.warnings
        return [w for w in invoice.warnings if w != AMOUNT_DUE_UNKNOWN_WARNING]


class ManualAmountDueSerializer(serializers.Serializer):
    manual_amount_due = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )


class InvoiceUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("pdf_file",)

    def validate_pdf_file(self, value):
        if not value.name.lower().endswith(".pdf"):
            raise serializers.ValidationError("Допускаются только PDF-файлы.")
        if value.size > 20 * 1024 * 1024:
            raise serializers.ValidationError("Размер файла не должен превышать 20 МБ.")
        header = value.read(5)
        value.seek(0)
        if header != b"%PDF-":
            raise serializers.ValidationError(
                "Файл не является валидным PDF (отсутствует сигнатура %PDF-)."
            )
        return value

from decimal import Decimal

from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = Payment
        fields = ("id", "invoice", "user", "amount", "payment_date", "note", "created_at")
        read_only_fields = ("id", "invoice", "user", "created_at")

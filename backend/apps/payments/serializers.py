from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("id", "invoice", "user", "amount", "payment_date", "note", "created_at")
        read_only_fields = ("id", "invoice", "user", "created_at")

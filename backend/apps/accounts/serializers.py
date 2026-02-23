from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("email", "password")

    def validate(self, attrs):
        if User.objects.exists():
            raise serializers.ValidationError(
                "Регистрация закрыта: администратор уже существует."
            )
        return attrs

    def create(self, validated_data):
        email = validated_data["email"]
        return User.objects.create_superuser(
            username=email,
            email=email,
            password=validated_data["password"],
        )


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD  # "email"

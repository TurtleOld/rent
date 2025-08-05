from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Profile


class UserRegistrationForm(UserCreationForm):
    """Форма регистрации пользователя"""

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Email"}
        ),
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Имя"}),
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Фамилия"}
        ),
    )

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Имя пользователя"}
        )
        self.fields["password1"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Пароль"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Подтвердите пароль"}
        )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email


class UserLoginForm(AuthenticationForm):
    """Форма входа пользователя"""

    username = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Имя пользователя или Email"}
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Пароль"}
        )
    )


class ProfileUpdateForm(forms.ModelForm):
    """Форма обновления профиля"""

    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        required=True, widget=forms.EmailInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = Profile
        fields = ("phone", "address", "birth_date", "avatar")
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "birth_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "avatar": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.user.first_name = self.cleaned_data["first_name"]
            profile.user.last_name = self.cleaned_data["last_name"]
            profile.user.email = self.cleaned_data["email"]
            profile.user.save()
            profile.save()
        return profile

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import CustomUser

class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password']
        widgets = {
            'username': forms.TextInput(attrs={"placeholder": "Enter username"}),
            'email': forms.EmailInput(attrs={"placeholder": "Enter email (optional)"}),
        }

class UserLoginForm(AuthenticationForm):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)

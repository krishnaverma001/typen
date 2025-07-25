from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Avatar", {"fields": ("image",)}),
    )


admin.site.register(CustomUser, CustomUserAdmin)

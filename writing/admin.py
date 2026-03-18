from django.contrib import admin
from .models import UserImage, UsageStats, Generation

admin.site.register(Generation)
admin.site.register(UserImage)
admin.site.register(UsageStats)

# writings.models.py

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

from django.db import models
from django.conf import settings

def user_directory_path(instance, filename):
    return f'user/{instance.user.username}/{filename}'

class UserImage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.FileField(upload_to=user_directory_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image by {self.user} at {self.created_at}" if self.user else f"Anonymous image at {self.created_at}"


class UsageStats(models.Model):
    total_visitors = models.PositiveIntegerField(default=0)
    total_generators = models.PositiveIntegerField(default=0)

    @classmethod
    def get(cls):
        stats, _ = cls.objects.get_or_create(pk=1)
        return stats

    @classmethod
    def increment_visitors(cls):
        cls.objects.update_or_create(
            pk=1,
            defaults={"total_visitors": cls.get().total_visitors + 1,
                      "total_generators": cls.get().total_generators}
        )

    @classmethod
    def increment_generators(cls):
        cls.objects.update_or_create(
            pk=1,
            defaults={"total_visitors": cls.get().total_visitors,
                      "total_generators": cls.get().total_generators + 1}
        )

    def __str__(self):
        return f"Visitors: {self.total_visitors}, Generators: {self.total_generators}"
# user/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

def user_avatar_path(instance, filename):
    return f'media/user/{instance.user.username}/profile/{filename}'

class CustomUser(AbstractUser):
    image = models.ImageField(upload_to=user_avatar_path, blank=True, null=True)

    def __str__(self):
        return self.username

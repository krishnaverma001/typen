# user/signals.py

from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from decouple import config
import logging

logger = logging.getLogger(__name__)

@receiver(post_migrate)
def create_superuser_signal(sender, **kwargs):
    if sender.label != 'user':
        return
     
    User = get_user_model()

    try:
        username = config("DJANGO_SU_NAME")
        email = config("DJANGO_SU_EMAIL")
        password = config("DJANGO_SU_PASS")
    except:
        logger.warning("Superuser env variables not set. Skipping superuser creation.")
        return

    if User.objects.filter(username=username).exists():
        return

    User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
    )
    logger.info(f"Superuser '{username}' created.")
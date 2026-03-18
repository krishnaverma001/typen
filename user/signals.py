from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from decouple import config

@receiver(post_migrate)
def create_superuser_signal(sender, **kwargs):
    if sender.name == 'auth':
        return
     
    User = get_user_model()

    try:
        username = config("DJANGO_SU_NAME")
        email = config("DJANGO_SU_EMAIL")
        password = config("DJANGO_SU_PASS")
    except:
        print("⚠ Superuser env variables not set. Skipping superuser creation.")
        return

    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username=username, email=email, password=password)
        print(f"Superuser '{username}' created.")
    else:
        print(f"ℹ Superuser '{username}' already exists.")
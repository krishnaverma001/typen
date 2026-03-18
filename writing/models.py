# writings.models.py

import uuid
from django.db import models
from django.conf import settings

def generation_file_path(instance, filename):
    """Generate file path with session_id: user/{username}/{session_id}/{filename}"""
    return f'user/{instance.generation.user.username}/{instance.generation.session_id}/{filename}'


class Generation(models.Model):
    """Groups multiple generated pages from a single handwriting generation session."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='generations')
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    text_input = models.TextField(help_text="Original text used for generation")
    
    # Generation parameters (stored as JSON for extensibility)
    parameters = models.JSONField(default=dict, help_text="Generation parameters: style, bias, stroke_width, use_margins")
    
    # Generation metadata
    pages_generated = models.PositiveIntegerField(default=0)
    generation_time = models.FloatField(default=0.0, help_text="Generation time in seconds")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"Generation by {self.user} on {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"


class UserImage(models.Model):
    generation = models.ForeignKey(Generation, on_delete=models.CASCADE, related_name='pages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.FileField(upload_to=generation_file_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['generation']),
            models.Index(fields=['user', '-created_at']),
        ]

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
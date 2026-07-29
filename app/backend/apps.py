"""Django application configuration for backend-owned components."""

from django.apps import AppConfig


class BackendConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backend"
    verbose_name = "DreamEscapes Backend"

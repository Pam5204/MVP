"""Django application metadata for the public HTTP API package."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """Register the API package with a stable model-key type and display name."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'api'
    verbose_name = "DreamEscapes API"

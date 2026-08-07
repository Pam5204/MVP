"""URL configuration for the dedicated DreamEscapes API process."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def api_root(_request):
    """Return a safe service marker instead of serving APP-VM assets."""
    return JsonResponse(
        {
            "success": True,
            "message": "DreamEscapes API service. Use /api/health for health checks.",
        }
    )


urlpatterns = [
    path("", api_root),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]

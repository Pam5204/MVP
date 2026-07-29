"""URL configuration for the App/API backend."""

from pathlib import Path

from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def frontend_index(_request):
    """Serve the single-page frontend at the Django root URL."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise Http404("Frontend index.html not found")
    return FileResponse(index_path.open("rb"), content_type="text/html")


def frontend_asset(_request, filename):
    """Serve the small set of frontend files referenced by index.html."""
    allowed_assets = {
        "styles.css": "text/css",
        "config.js": "application/javascript",
        "logic.js": "application/javascript",
        "app.js": "application/javascript",
    }
    if filename not in allowed_assets:
        raise Http404("Frontend asset not found")

    asset_path = FRONTEND_DIR / filename
    if not asset_path.exists():
        raise Http404("Frontend asset not found")
    return FileResponse(asset_path.open("rb"), content_type=allowed_assets[filename])


urlpatterns = [
    path("", frontend_index),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("<str:filename>", frontend_asset),
]

"""Destination search/details orchestration with DB-first cache behavior."""

import hashlib
import json
import re
from datetime import timedelta

from django.utils import timezone

from backend.models import DestinationCache, SearchHistory
from backend.services.errors import UpstreamServiceError, ValidationServiceError
from backend.services.event_service import emit_event
from backend.services.geoapify_service import (
    GeoapifyServiceError,
    get_destination_details as geoapify_destination_details,
    search_destinations as geoapify_search_destinations,
)

CACHE_TTL = timedelta(hours=24)
MAX_SEARCH_LIMIT = 50


def normalize_query(value):
    """Normalize user search text for stable cache lookup keys."""
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _cache_key(kind, *, place_id="", query="", country="", category="", attraction_type=""):
    components = {
        "kind": kind,
        "place_id": normalize_query(place_id),
        "query": normalize_query(query),
        "country": normalize_query(country),
        "category": normalize_query(category),
        "attraction_type": normalize_query(attraction_type),
    }
    digest = hashlib.sha256(
        json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{kind}:{digest}"


def _cache_metadata(cache, status, warning=""):
    return {
        "cache_status": status,
        "cache_warning": warning,
        "cached_at": cache.cached_at.isoformat() if cache else None,
        "expires_at": cache.expires_at.isoformat() if cache else None,
    }


def _fresh(cache):
    return bool(cache and cache.expires_at > timezone.now())


def _record_search(user, query, country, category, attraction_type, results):
    SearchHistory.objects.create(
        user=user,
        query=query,
        country_filter=country,
        category_filter=category,
        attraction_type_filter=attraction_type,
        place_id=results[0].get("place_id", "") if results else "",
    )


def search_destinations(filters, *, user=None, correlation_id=None):
    """Return a fresh cache hit or refresh normalized results through Geoapify."""
    name = normalize_query(filters.get("name"))
    keyword = normalize_query(filters.get("keyword"))
    country = normalize_query(filters.get("country"))
    category = normalize_query(filters.get("category"))
    attraction_type = normalize_query(
        filters.get("attraction_type", filters.get("attractionType"))
    )
    query = name or keyword or country
    if not query:
        raise ValidationServiceError(
            "Enter a destination name, keyword, or country."
        )
    if category == "all":
        category = ""
    if attraction_type == "all":
        attraction_type = ""
    try:
        limit = int(filters.get("limit", 20))
    except (TypeError, ValueError) as error:
        raise ValidationServiceError("Limit must be a whole number.") from error
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ValidationServiceError("Limit must be between 1 and 50.")

    key = _cache_key(
        "search",
        query=query,
        country=country,
        category=category,
        attraction_type=attraction_type,
    )
    cache = DestinationCache.objects.filter(cache_key=key).first()
    if _fresh(cache):
        results = cache.payload.get("results", [])
        _record_search(user, query, country, category, attraction_type, results)
        return {
            "query": query,
            "count": len(results),
            "results": results,
            **_cache_metadata(cache, "fresh"),
        }

    emit_event(
        "cache.refresh.requested",
        {"message": "Destination search cache refresh requested"},
        correlation_id=correlation_id,
        place_id=cache.place_id if cache else None,
    )
    try:
        upstream = geoapify_search_destinations(
            name=name,
            keyword=keyword,
            country=country,
            category=category,
            attraction_type=attraction_type,
            limit=limit,
        )
    except (GeoapifyServiceError, ValueError) as error:
        emit_event(
            "api.geoapify.unavailable",
            {"message": "Geoapify destination search failed"},
            correlation_id=correlation_id,
            error_code="GEOAPIFY_UNAVAILABLE",
        )
        emit_event(
            "api.failure",
            {"message": "Destination API request failed"},
            correlation_id=correlation_id,
            error_code="DESTINATION_API_FAILURE",
        )
        if cache:
            results = cache.payload.get("results", [])
            emit_event(
                "cache.stale.used",
                {"message": "Stale destination search cache used"},
                correlation_id=correlation_id,
                place_id=cache.place_id or None,
            )
            _record_search(user, query, country, category, attraction_type, results)
            return {
                "query": query,
                "count": len(results),
                "results": results,
                **_cache_metadata(
                    cache,
                    "stale",
                    "Cached destination data may be out of date.",
                ),
            }
        raise UpstreamServiceError(
            "Destination information is temporarily unavailable."
        ) from error

    now = timezone.now()
    results = upstream["results"]
    location = upstream["location"]
    cache, _created = DestinationCache.objects.update_or_create(
        cache_key=key,
        defaults={
            "place_id": location.get("place_id", ""),
            "normalized_query": query,
            "country": country,
            "categories": category,
            "attraction_type": attraction_type,
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "destination_name": location.get("name", ""),
            "destination_description": location.get("description", ""),
            "attractions": results,
            "nearby_attractions": [],
            "formatted_address": location.get("formatted_address", ""),
            "payload": {"location": location, "results": results},
            "raw_api_response": upstream.get("raw_api_response", {}),
            "cached_at": now,
            "expires_at": now + CACHE_TTL,
        },
    )
    emit_event(
        "cache.refresh.completed",
        {"message": "Destination search cache refreshed"},
        correlation_id=correlation_id,
        place_id=location.get("place_id") or None,
    )
    emit_event(
        "cache.destination.updated",
        {"message": "Destination cache updated"},
        correlation_id=correlation_id,
        place_id=location.get("place_id") or None,
    )
    _record_search(user, query, country, category, attraction_type, results)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        **_cache_metadata(cache, "refreshed"),
    }


def get_destination_details(place_id, *, user=None, correlation_id=None):
    """Return cached details or fetch details and nearby POIs from Geoapify."""
    place_id = str(place_id or "").strip()
    if not place_id:
        raise ValidationServiceError("A destination place ID is required.")
    key = _cache_key("detail", place_id=place_id)
    cache = DestinationCache.objects.filter(cache_key=key).first()
    if _fresh(cache):
        return {
            "destination": cache.payload.get("destination", {}),
            **_cache_metadata(cache, "fresh"),
        }

    emit_event(
        "cache.refresh.requested",
        {"message": "Destination details cache refresh requested"},
        correlation_id=correlation_id,
        place_id=place_id,
    )
    try:
        upstream = geoapify_destination_details(place_id)
    except (GeoapifyServiceError, ValueError) as error:
        emit_event(
            "api.geoapify.unavailable",
            {"message": "Geoapify destination details failed"},
            correlation_id=correlation_id,
            place_id=place_id,
            error_code="GEOAPIFY_UNAVAILABLE",
        )
        emit_event(
            "api.failure",
            {"message": "Destination details request failed"},
            correlation_id=correlation_id,
            place_id=place_id,
            error_code="DESTINATION_API_FAILURE",
        )
        if cache:
            emit_event(
                "cache.stale.used",
                {"message": "Stale destination details cache used"},
                correlation_id=correlation_id,
                place_id=place_id,
            )
            return {
                "destination": cache.payload.get("destination", {}),
                **_cache_metadata(
                    cache,
                    "stale",
                    "Cached destination data may be out of date.",
                ),
            }
        raise UpstreamServiceError(
            "Destination information is temporarily unavailable."
        ) from error

    destination = upstream["destination"]
    now = timezone.now()
    cache, _created = DestinationCache.objects.update_or_create(
        cache_key=key,
        defaults={
            "place_id": place_id,
            "normalized_query": "",
            "country": destination.get("country", ""),
            "categories": ",".join(destination.get("categories", [])),
            "attraction_type": "",
            "latitude": destination.get("latitude"),
            "longitude": destination.get("longitude"),
            "destination_name": destination.get("name", ""),
            "destination_description": destination.get("description", ""),
            "attractions": destination.get("points_of_interest", []),
            "nearby_attractions": destination.get("nearby_attractions", []),
            "formatted_address": destination.get("formatted_address", ""),
            "payload": {"destination": destination},
            "raw_api_response": upstream.get("raw_api_response", {}),
            "cached_at": now,
            "expires_at": now + CACHE_TTL,
        },
    )
    emit_event(
        "cache.refresh.completed",
        {"message": "Destination details cache refreshed"},
        correlation_id=correlation_id,
        place_id=place_id,
    )
    emit_event(
        "cache.destination.updated",
        {"message": "Destination details cache updated"},
        correlation_id=correlation_id,
        place_id=place_id,
    )
    return {
        "destination": destination,
        **_cache_metadata(cache, "refreshed"),
    }


def recent_searches(user, limit=10):
    """Return an authenticated user's most recent search inputs."""
    rows = SearchHistory.objects.filter(user=user).order_by("-created_at")[:limit]
    return [
        {
            "search_id": row.search_id,
            "query": row.query,
            "country_filter": row.country_filter,
            "category_filter": row.category_filter,
            "attraction_type_filter": row.attraction_type_filter,
            "place_id": row.place_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

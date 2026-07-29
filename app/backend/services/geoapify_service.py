"""Reusable Geoapify geocoding, places, details, and nearby-place client."""

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"
PLACE_DETAILS_URL = "https://api.geoapify.com/v2/place-details"
REQUEST_TIMEOUT_SECONDS = 10
NEARBY_RADIUS_METERS = 5000

DEFAULT_ATTRACTION_CATEGORIES = (
    "entertainment.culture,"
    "entertainment.museum,"
    "heritage,"
    "leisure,"
    "natural,"
    "national_park,"
    "tourism"
)

CATEGORY_MAP = {
    "family-friendly": "leisure,entertainment,tourism",
    "outdoor": "leisure,natural,national_park",
    "budget": "tourism,leisure",
    "culture": "entertainment.culture,entertainment.museum,heritage",
}

ATTRACTION_TYPE_MAP = {
    "museum": "entertainment.museum",
    "beach": "beach",
    "park": "leisure.park,national_park",
    "food": "catering",
}


class GeoapifyServiceError(Exception):
    """Raised when Geoapify cannot provide usable destination data."""


def _get_api_key():
    api_key = os.getenv("GEOAPIFY_API_KEY", "").strip()
    if not api_key or "replace" in api_key.lower():
        raise GeoapifyServiceError("Destination information is temporarily unavailable.")
    return api_key


def _make_request(url, params):
    """Send a bounded GET request and require a JSON object response."""
    safe_params = dict(params)
    safe_params["apiKey"] = _get_api_key()
    try:
        response = requests.get(
            url,
            params=safe_params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.Timeout as error:
        raise GeoapifyServiceError("Destination request timed out.") from error
    except requests.RequestException as error:
        raise GeoapifyServiceError(
            "Destination information is temporarily unavailable."
        ) from error
    try:
        result = response.json()
    except ValueError as error:
        raise GeoapifyServiceError(
            "Destination service returned an invalid response."
        ) from error
    if not isinstance(result, dict):
        raise GeoapifyServiceError(
            "Destination service returned an invalid response."
        )
    return result


def _point_coordinates(feature):
    properties = feature.get("properties") or {}
    latitude = properties.get("lat")
    longitude = properties.get("lon")
    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    if latitude is None and len(coordinates) >= 2 and isinstance(coordinates[1], (int, float)):
        latitude = coordinates[1]
    if longitude is None and len(coordinates) >= 2 and isinstance(coordinates[0], (int, float)):
        longitude = coordinates[0]
    return latitude, longitude


def _description(properties):
    datasource = properties.get("datasource") or {}
    raw = datasource.get("raw") or {}
    wiki = properties.get("wiki_and_media") or {}
    return (
        properties.get("description")
        or wiki.get("description")
        or raw.get("description")
        or properties.get("formatted")
        or ""
    )


def normalize_place(feature):
    """Normalize a GeoJSON feature into the app-standard destination shape."""
    properties = feature.get("properties") or {}
    latitude, longitude = _point_coordinates(feature)
    categories = properties.get("categories") or []
    if not isinstance(categories, list):
        categories = [str(categories)]
    return {
        "place_id": properties.get("place_id") or "",
        "name": (
            properties.get("name")
            or properties.get("address_line1")
            or properties.get("city")
            or "Unnamed destination"
        ),
        "city": properties.get("city") or properties.get("county") or "",
        "state": properties.get("state") or "",
        "country": properties.get("country") or "",
        "country_code": properties.get("country_code") or "",
        "categories": categories,
        "category": categories[0] if categories else "",
        "formatted_address": properties.get("formatted") or "",
        "address_line1": properties.get("address_line1") or "",
        "address_line2": properties.get("address_line2") or "",
        "latitude": latitude,
        "longitude": longitude,
        "distance": properties.get("distance"),
        "description": _description(properties),
    }


def find_location(search_text, country=""):
    """Resolve a city, destination name, or country into a Geoapify place."""
    cleaned = str(search_text or "").strip()
    country = str(country or "").strip()
    if not cleaned and not country:
        raise ValueError("A destination name, keyword, or country is required.")
    text = ", ".join(value for value in (cleaned, country) if value)
    params = {
        "text": text,
        "format": "geojson",
        "limit": 1,
        "lang": "en",
    }
    if len(country) == 2 and country.isalpha():
        params["filter"] = f"countrycode:{country.lower()}"
    response = _make_request(GEOCODING_URL, params)
    features = response.get("features") or []
    if not features:
        raise GeoapifyServiceError(f'No destination was found for "{text}".')
    location = normalize_place(features[0])
    if (
        not location["place_id"]
        or location["latitude"] is None
        or location["longitude"] is None
    ):
        raise GeoapifyServiceError("Destination coordinates were not available.")
    return location, response


def _selected_categories(category="", attraction_type=""):
    attraction_type = str(attraction_type or "").strip().lower()
    category = str(category or "").strip().lower()
    if attraction_type and attraction_type != "all":
        return ATTRACTION_TYPE_MAP.get(attraction_type, attraction_type)
    if category and category != "all":
        return CATEGORY_MAP.get(category, category)
    return DEFAULT_ATTRACTION_CATEGORIES


def search_destinations(
    *,
    name="",
    keyword="",
    country="",
    category="",
    attraction_type="",
    limit=20,
):
    """Search named attractions within a resolved destination boundary."""
    query = str(name or keyword or country).strip()
    location, geocoding_response = find_location(query, country)
    params = {
        "categories": _selected_categories(category, attraction_type),
        "filter": f"place:{location['place_id']}",
        "bias": f"proximity:{location['longitude']},{location['latitude']}",
        "conditions": "named",
        "limit": max(1, min(int(limit), 50)),
        "lang": "en",
    }
    name_filter = str(keyword or "").strip()
    if name_filter:
        params["name"] = name_filter
    places_response = _make_request(PLACES_URL, params)
    results = [normalize_place(feature) for feature in places_response.get("features") or []]
    results = [item for item in results if item["place_id"]]
    if name and location["place_id"] not in {item["place_id"] for item in results}:
        results.insert(0, location)
    return {
        "location": location,
        "results": results,
        "count": len(results),
        "raw_api_response": {
            "geocoding": geocoding_response,
            "places": places_response,
        },
    }


def get_destination_details(place_id, *, nearby_limit=12):
    """Load place details plus nearby attractions and points of interest."""
    place_id = str(place_id or "").strip()
    if not place_id:
        raise ValueError("A destination place ID is required.")
    details_response = _make_request(
        PLACE_DETAILS_URL,
        {"id": place_id, "features": "details", "lang": "en"},
    )
    features = details_response.get("features") or []
    if not features:
        raise GeoapifyServiceError("Destination details were not found.")
    detail_feature = next(
        (
            feature
            for feature in features
            if (feature.get("properties") or {}).get("feature_type") == "details"
        ),
        features[0],
    )
    destination = normalize_place(detail_feature)
    if not destination["place_id"]:
        destination["place_id"] = place_id

    nearby = []
    nearby_response: dict[str, Any] = {}
    if destination["latitude"] is not None and destination["longitude"] is not None:
        nearby_response = _make_request(
            PLACES_URL,
            {
                "categories": DEFAULT_ATTRACTION_CATEGORIES,
                "filter": (
                    f"circle:{destination['longitude']},"
                    f"{destination['latitude']},{NEARBY_RADIUS_METERS}"
                ),
                "bias": (
                    f"proximity:{destination['longitude']},"
                    f"{destination['latitude']}"
                ),
                "conditions": "named",
                "limit": max(1, min(int(nearby_limit), 50)),
                "lang": "en",
            },
        )
        nearby = [
            normalize_place(feature)
            for feature in nearby_response.get("features") or []
            if (feature.get("properties") or {}).get("place_id") != place_id
        ]

    destination["nearby_attractions"] = nearby
    destination["points_of_interest"] = nearby[:8]
    return {
        "destination": destination,
        "raw_api_response": {
            "details": details_response,
            "nearby": nearby_response,
        },
    }

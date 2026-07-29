"""Bucket-list validation, ownership enforcement, and persistence."""

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError

from backend.models import BucketListDestination
from backend.services.errors import ConflictError, NotFoundError, ValidationServiceError
from backend.services.event_service import emit_event

REQUIRED_SAVE_FIELDS = (
    "destination_name",
    "city",
    "country",
    "latitude",
    "longitude",
    "place_id",
)


def _required_text(payload, field):
    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValidationServiceError(
            f"{field.replace('_', ' ').capitalize()} is required."
        )
    return value


def _coordinates(payload):
    try:
        latitude = Decimal(str(payload.get("latitude")))
        longitude = Decimal(str(payload.get("longitude")))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationServiceError(
            "Latitude and longitude must be valid numbers."
        ) from error
    if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
        raise ValidationServiceError("Latitude or longitude is outside its valid range.")
    return latitude, longitude


def normalize_categories(value):
    """Store categories consistently while accepting arrays or comma strings."""
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    else:
        raise ValidationServiceError(
            "Categories must be a list or comma-separated string."
        )
    return ",".join(dict.fromkeys(values))


def serialize_bucket_item(item):
    """Return the frontend/API representation for one saved destination."""
    return {
        "bucket_item_id": item.bucket_item_id,
        "destination_name": item.destination_name,
        "city": item.city,
        "country": item.country,
        "categories": [
            value for value in item.categories.split(",") if value
        ],
        "latitude": float(item.latitude),
        "longitude": float(item.longitude),
        "place_id": item.place_id,
        "travel_type_label": item.travel_type_label,
        "saved_at": item.saved_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def list_bucket_list_items(user):
    """Return only destinations owned by the authenticated user."""
    items = BucketListDestination.objects.filter(user=user).order_by("-saved_at")
    return [serialize_bucket_item(item) for item in items]


def save_bucket_list_item(user, payload, *, correlation_id=None):
    """Validate and save a destination, rejecting per-user duplicates."""
    missing = [field for field in REQUIRED_SAVE_FIELDS if payload.get(field) in (None, "")]
    if missing:
        raise ValidationServiceError(
            "Missing required bucket-list fields: " + ", ".join(missing) + "."
        )
    latitude, longitude = _coordinates(payload)
    place_id = _required_text(payload, "place_id")

    if BucketListDestination.objects.filter(user=user, place_id=place_id).exists():
        emit_event(
            "bucketlist.destination.duplicate_rejected",
            {"message": "Duplicate destination save rejected"},
            correlation_id=correlation_id,
            user_id=user.user_id,
            place_id=place_id,
        )
        raise ConflictError("This destination is already in your bucket list.")

    try:
        item = BucketListDestination.objects.create(
            user=user,
            destination_name=_required_text(payload, "destination_name"),
            city=_required_text(payload, "city"),
            country=_required_text(payload, "country"),
            categories=normalize_categories(payload.get("categories")),
            latitude=latitude,
            longitude=longitude,
            place_id=place_id,
            travel_type_label=str(payload.get("travel_type_label", "")).strip(),
        )
    except IntegrityError as error:
        raise ConflictError(
            "This destination is already in your bucket list."
        ) from error

    emit_event(
        "bucketlist.destination.saved",
        {"message": "Destination saved"},
        correlation_id=correlation_id,
        user_id=user.user_id,
        place_id=item.place_id,
        bucket_item_id=item.bucket_item_id,
    )
    emit_event(
        "bucketlist.updated",
        {"message": "Bucket list updated"},
        correlation_id=correlation_id,
        user_id=user.user_id,
        bucket_item_id=item.bucket_item_id,
    )
    return serialize_bucket_item(item)


def _owned_item(user, bucket_item_id):
    item = BucketListDestination.objects.filter(
        user=user,
        bucket_item_id=bucket_item_id,
    ).first()
    if not item:
        raise NotFoundError("Bucket-list item was not found.")
    return item


def update_bucket_list_item(user, bucket_item_id, payload, *, correlation_id=None):
    """Update category/travel-label fields on an owned bucket-list item."""
    item = _owned_item(user, bucket_item_id)
    changed = []
    if "categories" in payload:
        item.categories = normalize_categories(payload.get("categories"))
        changed.append("categories")
    if "travel_type_label" in payload or "label" in payload:
        item.travel_type_label = str(
            payload.get("travel_type_label", payload.get("label", ""))
        ).strip()
        changed.append("travel_type_label")
    if not changed:
        raise ValidationServiceError(
            "Provide categories or a travel-type label to update."
        )
    item.save(update_fields=[*changed, "updated_at"])

    emit_event(
        "bucketlist.destination.updated",
        {"message": "Saved destination updated"},
        correlation_id=correlation_id,
        user_id=user.user_id,
        place_id=item.place_id,
        bucket_item_id=item.bucket_item_id,
    )
    return serialize_bucket_item(item)


def delete_bucket_list_item(user, bucket_item_id, *, correlation_id=None):
    """Delete an owned item without revealing another user's records."""
    item = _owned_item(user, bucket_item_id)
    identifiers = {
        "bucket_item_id": item.bucket_item_id,
        "place_id": item.place_id,
    }
    item.delete()
    emit_event(
        "bucketlist.destination.deleted",
        {"message": "Saved destination deleted"},
        correlation_id=correlation_id,
        user_id=user.user_id,
        place_id=identifiers["place_id"],
        bucket_item_id=identifiers["bucket_item_id"],
    )
    return identifiers

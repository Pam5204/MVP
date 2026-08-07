"""Authenticated destination-review validation, persistence, and events."""

from backend.models import DestinationReference, DestinationReview
from backend.services.errors import ValidationServiceError
from backend.services.event_service import emit_event


def _required_text(payload, field, maximum):
    value = str(payload.get(field, "")).strip()
    label = field.replace("_", " ").capitalize()
    if not value:
        raise ValidationServiceError(f"{label} is required.")
    if len(value) > maximum:
        raise ValidationServiceError(f"{label} must be {maximum} characters or fewer.")
    return value


def _optional_text(payload, field, maximum):
    value = str(payload.get(field, "")).strip()
    if len(value) > maximum:
        label = field.replace("_", " ").capitalize()
        raise ValidationServiceError(f"{label} must be {maximum} characters or fewer.")
    return value


def _rating(value):
    if isinstance(value, bool):
        raise ValidationServiceError("Rating must be a whole number from 1 to 5.")
    try:
        rating = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationServiceError(
            "Rating must be a whole number from 1 to 5."
        ) from error
    if str(value).strip() != str(rating) or rating < 1 or rating > 5:
        raise ValidationServiceError("Rating must be a whole number from 1 to 5.")
    return rating


def serialize_review(review):
    """Return one review without exposing account credentials or private data."""
    return {
        "review_id": review.review_id,
        "place_id": review.destination.place_id,
        "destination_name": review.destination.destination_name,
        "user_id": review.user_id,
        "username": review.user.username,
        "comment": review.comment,
        "rating": review.rating,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
    }


def list_destination_reviews(place_id):
    """Return newest-first persisted reviews for one stable destination ID."""
    normalized_place_id = str(place_id or "").strip()
    if not normalized_place_id:
        raise ValidationServiceError("Place ID is required.")
    reviews = (
        DestinationReview.objects.filter(destination__place_id=normalized_place_id)
        .select_related("destination", "user")
        .order_by("-created_at", "-review_id")
    )
    return [serialize_review(review) for review in reviews]


def submit_destination_review(user, place_id, payload, *, correlation_id=None):
    """Persist a validated review and emit its traceable RabbitMQ event."""
    route_place_id = str(place_id or "").strip()
    body_place_id = str(payload.get("place_id", route_place_id)).strip()
    if not route_place_id or route_place_id != body_place_id:
        raise ValidationServiceError("The review place ID does not match the route.")
    if len(route_place_id) > 255:
        raise ValidationServiceError("Place ID must be 255 characters or fewer.")

    destination_name = _required_text(payload, "destination_name", 255)
    city = _optional_text(payload, "city", 150)
    country = _optional_text(payload, "country", 150)
    formatted_address = _optional_text(payload, "formatted_address", 2000)
    comment = _required_text(payload, "comment", 2000)
    rating = _rating(payload.get("rating"))
    destination, _created = DestinationReference.objects.update_or_create(
        place_id=route_place_id,
        defaults={
            "destination_name": destination_name,
            "city": city,
            "country": country,
            "formatted_address": formatted_address,
        },
    )
    review = DestinationReview.objects.create(
        user=user,
        destination=destination,
        comment=comment,
        rating=rating,
    )
    emit_event(
        "review.submitted",
        {"message": "Destination review submitted"},
        correlation_id=correlation_id,
        user_id=user.user_id,
        review_id=review.review_id,
        place_id=destination.place_id,
        rating=review.rating,
    )
    return serialize_review(review)

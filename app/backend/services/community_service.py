"""Required community-post CRUD, search, ownership, and moderation rules."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db.models import Q

from backend.models import AdminAuditLog, CommunityPost, UserAccount
from backend.services.errors import ForbiddenError, NotFoundError, ValidationServiceError
from backend.services.event_service import emit_event


PICTURE_URL_VALIDATOR = URLValidator(schemes=("http", "https"))


def _text(payload, field, *, required=False, minimum=0, maximum):
    value = str(payload.get(field, "")).strip()
    label = field.replace("_", " ").capitalize()
    if required and not value:
        raise ValidationServiceError(f"{label} is required.")
    if value and len(value) < minimum:
        raise ValidationServiceError(f"{label} must be at least {minimum} characters.")
    if len(value) > maximum:
        raise ValidationServiceError(f"{label} must be {maximum} characters or fewer.")
    return value


def _post_type(value):
    normalized = str(value or "").strip().lower()
    allowed = {choice[0] for choice in CommunityPost.TYPE_CHOICES}
    if normalized not in allowed:
        raise ValidationServiceError("Post type must be either experience or question.")
    return normalized


def _picture_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > 1000:
        raise ValidationServiceError("Picture URL must be 1000 characters or fewer.")
    try:
        PICTURE_URL_VALIDATOR(url)
    except DjangoValidationError as error:
        raise ValidationServiceError(
            "Picture URL must be a valid HTTP or HTTPS address."
        ) from error
    return url


def serialize_post(post, viewer):
    """Return display data plus viewer-specific controls for the frontend."""
    is_admin = viewer.role == UserAccount.ROLE_ADMIN
    is_owner = viewer.user_id == post.author_id
    return {
        "post_id": post.post_id,
        "author_user_id": post.author_id,
        "author_username": post.author.username,
        "post_type": post.post_type,
        "title": post.title,
        "body": post.body,
        "destination_name": post.destination_name,
        "picture_url": post.picture_url,
        "moderation_status": post.moderation_status,
        "created_at": post.created_at.isoformat(),
        "updated_at": post.updated_at.isoformat(),
        "can_edit": is_owner or is_admin,
        "can_delete": is_owner or is_admin,
        "can_moderate": is_admin,
    }


def _visible_posts_for(viewer):
    posts = CommunityPost.objects.select_related("author")
    if viewer.role == UserAccount.ROLE_ADMIN:
        return posts
    return posts.filter(
        Q(moderation_status=CommunityPost.STATUS_VISIBLE) | Q(author=viewer)
    )


def list_community_posts(viewer, query=""):
    """Search visible displayed post text with a user-entered query."""
    query = str(query or "").strip()
    if len(query) > 200:
        raise ValidationServiceError("Search query must be 200 characters or fewer.")
    posts = _visible_posts_for(viewer)
    if query:
        posts = posts.filter(
            Q(title__icontains=query)
            | Q(body__icontains=query)
            | Q(destination_name__icontains=query)
        )
    posts = posts.order_by("-created_at", "-post_id")
    return [serialize_post(post, viewer) for post in posts]


def _load_post(viewer, post_id):
    post = _visible_posts_for(viewer).filter(post_id=post_id).first()
    if not post:
        raise NotFoundError("Community post was not found.")
    return post


def get_community_post(viewer, post_id):
    """Return one visible, owned, or administrator-visible post."""
    return serialize_post(_load_post(viewer, post_id), viewer)


def create_community_post(author, payload, *, correlation_id=None):
    """Create a required travel-experience or question post."""
    post = CommunityPost.objects.create(
        author=author,
        post_type=_post_type(payload.get("post_type")),
        title=_text(payload, "title", required=True, minimum=3, maximum=160),
        body=_text(payload, "body", required=True, minimum=10, maximum=5000),
        destination_name=_text(payload, "destination_name", maximum=255),
        picture_url=_picture_url(payload.get("picture_url")),
    )
    emit_event(
        "community.post.created",
        {"message": "Community post created"},
        correlation_id=correlation_id,
        user_id=author.user_id,
        post_id=post.post_id,
        post_type=post.post_type,
    )
    return serialize_post(post, author)


def update_community_post(viewer, post_id, payload, *, correlation_id=None):
    """Update an owned post; administrators may assist or correct a post."""
    post = _load_post(viewer, post_id)
    if post.author_id != viewer.user_id and viewer.role != UserAccount.ROLE_ADMIN:
        raise ForbiddenError("You can update only your own community posts.")

    changed = []
    validators = {
        "post_type": lambda value: _post_type(value),
        "title": lambda _value: _text(
            payload, "title", required=True, minimum=3, maximum=160
        ),
        "body": lambda _value: _text(
            payload, "body", required=True, minimum=10, maximum=5000
        ),
        "destination_name": lambda _value: _text(
            payload, "destination_name", maximum=255
        ),
        "picture_url": _picture_url,
    }
    for field, validator in validators.items():
        if field in payload:
            setattr(post, field, validator(payload.get(field)))
            changed.append(field)
    if not changed:
        raise ValidationServiceError("Provide at least one post field to update.")
    post.save(update_fields=[*changed, "updated_at"])
    emit_event(
        "community.post.updated",
        {"message": "Community post updated"},
        correlation_id=correlation_id,
        user_id=viewer.user_id,
        post_id=post.post_id,
    )
    return serialize_post(post, viewer)


def delete_community_post(viewer, post_id, *, correlation_id=None):
    """Delete an owned post or allow an administrator to remove one."""
    post = _load_post(viewer, post_id)
    if post.author_id != viewer.user_id and viewer.role != UserAccount.ROLE_ADMIN:
        raise ForbiddenError("You can delete only your own community posts.")
    identifiers = {"post_id": post.post_id, "author_user_id": post.author_id}
    post.delete()
    emit_event(
        "community.post.deleted",
        {"message": "Community post deleted"},
        correlation_id=correlation_id,
        user_id=viewer.user_id,
        **identifiers,
    )
    return identifiers


def moderate_community_post(admin, post_id, status, *, correlation_id=None):
    """Allow only administrators to hide or restore a community post."""
    if admin.role != UserAccount.ROLE_ADMIN:
        raise ForbiddenError("Administrator access is required.")
    normalized = str(status or "").strip().lower()
    allowed = {choice[0] for choice in CommunityPost.STATUS_CHOICES}
    if normalized not in allowed:
        raise ValidationServiceError("Moderation status must be visible or hidden.")
    post = CommunityPost.objects.select_related("author").filter(post_id=post_id).first()
    if not post:
        raise NotFoundError("Community post was not found.")
    post.moderation_status = normalized
    post.save(update_fields=["moderation_status", "updated_at"])
    audit = AdminAuditLog.objects.create(
        admin_user=admin,
        action_type="community_post_moderated",
        target_type="community_post",
        target_id=str(post.post_id),
        notes=f"Set community post {post.post_id} to {normalized}.",
    )
    emit_event(
        "community.post.moderated",
        {"message": "Community post moderation status changed"},
        correlation_id=correlation_id,
        user_id=admin.user_id,
        post_id=post.post_id,
        moderation_status=normalized,
        audit_id=audit.audit_id,
    )
    return serialize_post(post, admin)

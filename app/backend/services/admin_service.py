"""Administrator authorization, account management, review, and auditing."""

from backend.models import AdminAuditLog, DestinationCache, UserAccount
from backend.services.auth_service import current_auth_session, public_user
from backend.services.errors import ForbiddenError, NotFoundError, ValidationServiceError
from backend.services.event_service import emit_event


def require_admin_user(request, *, correlation_id=None):
    """Require a current enabled administrator and record denied attempts."""
    session = current_auth_session(request) or {}
    user = None
    if session.get("user_id"):
        user = UserAccount.objects.filter(user_id=session["user_id"]).first()
    if (
        not user
        or user.role != UserAccount.ROLE_ADMIN
        or user.account_status != UserAccount.STATUS_ENABLED
    ):
        emit_event(
            "admin.unauthorized.attempted",
            {"message": "Unauthorized admin access attempted"},
            correlation_id=correlation_id,
            user_id=user.user_id if user else None,
            status="denied",
        )
        raise ForbiddenError("Administrator access is required.")
    return user


def _audit(admin, action_type, target_type, target_id, notes, *, status="success"):
    return AdminAuditLog.objects.create(
        admin_user=admin,
        action_type=action_type,
        target_type=target_type,
        target_id=str(target_id),
        notes=notes,
        status=status,
    )


def _emit_admin_action(
    event_type,
    admin,
    audit,
    *,
    correlation_id=None,
    target_id=None,
):
    emit_event(
        event_type,
        {"message": audit.notes},
        correlation_id=correlation_id,
        admin_user_id=admin.user_id,
        target_id=str(target_id) if target_id is not None else None,
        status=audit.status,
    )
    emit_event(
        "admin.audit.created",
        {"message": "Admin audit record created"},
        correlation_id=correlation_id,
        admin_user_id=admin.user_id,
        target_id=str(audit.audit_id),
        status=audit.status,
    )


def list_users(request, *, correlation_id=None):
    require_admin_user(request, correlation_id=correlation_id)
    return [public_user(user) for user in UserAccount.objects.order_by("user_id")]


def update_user_role(request, user_id, role, *, correlation_id=None):
    admin = require_admin_user(request, correlation_id=correlation_id)
    if role not in {UserAccount.ROLE_USER, UserAccount.ROLE_ADMIN}:
        raise ValidationServiceError("Role must be user or admin.")
    target = UserAccount.objects.filter(user_id=user_id).first()
    if not target:
        raise NotFoundError("User was not found.")
    target.role = role
    target.save(update_fields=["role", "updated_at"])
    audit = _audit(
        admin,
        "user_role_changed",
        "user",
        target.user_id,
        f"Role changed to {role}.",
    )
    _emit_admin_action(
        "admin.user.role_changed",
        admin,
        audit,
        correlation_id=correlation_id,
        target_id=target.user_id,
    )
    return public_user(target)


def update_user_status(request, user_id, status, *, correlation_id=None):
    admin = require_admin_user(request, correlation_id=correlation_id)
    if status not in {UserAccount.STATUS_ENABLED, UserAccount.STATUS_DISABLED}:
        raise ValidationServiceError("Status must be enabled or disabled.")
    target = UserAccount.objects.filter(user_id=user_id).first()
    if not target:
        raise NotFoundError("User was not found.")
    target.account_status = status
    target.save(update_fields=["account_status", "updated_at"])
    audit = _audit(
        admin,
        "user_status_changed",
        "user",
        target.user_id,
        f"Account status changed to {status}.",
    )
    _emit_admin_action(
        "admin.user.status_changed",
        admin,
        audit,
        correlation_id=correlation_id,
        target_id=target.user_id,
    )
    return public_user(target)


def list_cached_destinations(request, *, correlation_id=None):
    require_admin_user(request, correlation_id=correlation_id)
    rows = DestinationCache.objects.order_by("-updated_at")
    return [
        {
            "cache_id": row.cache_id,
            "place_id": row.place_id,
            "destination_name": row.destination_name,
            "country": row.country,
            "categories": row.categories,
            "formatted_address": row.formatted_address,
            "source_api": row.source_api,
            "cached_at": row.cached_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
        }
        for row in rows
    ]


def review_destination(request, cache_id, *, correlation_id=None):
    admin = require_admin_user(request, correlation_id=correlation_id)
    cache = DestinationCache.objects.filter(cache_id=cache_id).first()
    if not cache:
        raise NotFoundError("Cached destination was not found.")
    audit = _audit(
        admin,
        "destination_reviewed",
        "destination_cache",
        cache.cache_id,
        f"Reviewed cached destination {cache.destination_name or cache.place_id}.",
    )
    _emit_admin_action(
        "admin.destination.reviewed",
        admin,
        audit,
        correlation_id=correlation_id,
        target_id=cache.cache_id,
    )
    return {
        "cache_id": cache.cache_id,
        "place_id": cache.place_id,
        "destination_name": cache.destination_name,
        "reviewed": True,
    }


def list_audit_logs(request, *, correlation_id=None):
    require_admin_user(request, correlation_id=correlation_id)
    rows = AdminAuditLog.objects.select_related("admin_user").order_by("-created_at")
    return [
        {
            "audit_id": row.audit_id,
            "admin_user_id": row.admin_user_id,
            "admin_email": row.admin_user.email,
            "action_type": row.action_type,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "notes": row.notes,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

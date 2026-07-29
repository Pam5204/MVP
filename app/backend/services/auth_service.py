"""Authentication, profile, and signed-session business logic."""

import re
from datetime import datetime, timezone
from uuid import uuid4

import bcrypt
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from backend.models import UserAccount
from backend.services.errors import (
    AuthenticationRequiredError,
    ConflictError,
    InvalidCredentialsError,
    UpstreamServiceError,
    ValidationServiceError,
)
from backend.services.event_service import emit_event
from mq.rabbitmq import request_auth_response

AUTH_TIMEOUT_SECONDS = 15
SESSION_AGE_SECONDS = 30 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{1,98}[A-Za-z0-9]$")
GENERIC_LOGIN_ERROR = "Invalid email or password."


def normalize_email(value):
    """Validate and normalize a user email address."""
    email = str(value or "").strip().lower()
    if not email:
        raise ValidationServiceError("Email is required.")
    try:
        validate_email(email)
    except DjangoValidationError as error:
        raise ValidationServiceError("Enter a valid email address.") from error
    return email


def validate_username(value):
    """Require a simple display-safe username."""
    username = str(value or "").strip()
    if not username:
        raise ValidationServiceError("Username is required.")
    if len(username) < 3 or len(username) > 100 or not USERNAME_PATTERN.fullmatch(username):
        raise ValidationServiceError(
            "Username must be 3-100 characters and use letters, numbers, spaces, "
            "periods, underscores, or hyphens."
        )
    return username


def validate_password(value, *, required=True):
    """Validate a plaintext password without logging or returning it."""
    password = str(value or "")
    if not password and not required:
        return ""
    if not password:
        raise ValidationServiceError("Password is required.")
    if len(password) < 8:
        raise ValidationServiceError("Password must be at least 8 characters.")
    if len(password.encode("utf-8")) > 72:
        raise ValidationServiceError("Password must be 72 bytes or fewer.")
    return password


def public_user(user):
    """Serialize only fields that are safe for API responses and sessions."""
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "travel_preferences": user.travel_preferences,
        "account_status": user.account_status,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _auth_message(message_type, payload, correlation_id=None):
    """Build an auth command; the MQ client assigns its private reply queue."""
    return {
        "type": message_type,
        "correlation_id": correlation_id or str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def _request_auth_command(message):
    try:
        return request_auth_response(message, timeout_seconds=AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        raise
    except Exception as error:
        raise UpstreamServiceError(
            "Authentication service is temporarily unavailable."
        ) from error


def register_user(username, email, password, *, correlation_id=None):
    """Register exclusively through the DB-role RabbitMQ consumer."""
    username = validate_username(username)
    email = normalize_email(email)
    password = validate_password(password)

    message = _auth_message(
        "auth.register.request",
        {"username": username, "email": email, "password": password},
        correlation_id,
    )
    response = _request_auth_command(message)
    if not response.get("success"):
        raise ConflictError(
            response.get("error") or "An account with that email already exists."
        )
    payload = response.get("payload", {})
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username", username),
        "email": payload.get("email", email),
        "role": payload.get("role", UserAccount.ROLE_USER),
        "account_status": payload.get(
            "account_status", UserAccount.STATUS_ENABLED
        ),
    }


def authenticate_user(email, password, *, correlation_id=None):
    """Authenticate exclusively through the DB-role RabbitMQ consumer."""
    email = normalize_email(email)
    password = validate_password(password)

    message = _auth_message(
        "auth.login.request",
        {"email": email, "password": password},
        correlation_id,
    )
    response = _request_auth_command(message)
    if not response.get("success"):
        raise InvalidCredentialsError(GENERIC_LOGIN_ERROR)
    return response.get("payload", {})


def store_auth_session(request, user_payload):
    """Store safe identity fields in the signed application session."""
    request.session["auth_user"] = {
        "user_id": user_payload.get("user_id"),
        "email": user_payload.get("email"),
        "username": user_payload.get("username"),
        "role": user_payload.get("role", UserAccount.ROLE_USER),
        "account_status": user_payload.get(
            "account_status", UserAccount.STATUS_ENABLED
        ),
        "login_at": datetime.now(timezone.utc).isoformat(),
    }
    request.session.set_expiry(SESSION_AGE_SECONDS)


def current_auth_session(request):
    return request.session.get("auth_user")


def require_authenticated_user(request):
    """Load the current enabled user and reject stale/invalid sessions."""
    session = current_auth_session(request)
    if not session or not session.get("user_id"):
        raise AuthenticationRequiredError("Authentication required.")
    user = UserAccount.objects.filter(user_id=session["user_id"]).first()
    if not user or user.account_status != UserAccount.STATUS_ENABLED:
        clear_auth_session(request)
        raise AuthenticationRequiredError("Authentication required.")
    return user


def clear_auth_session(request, *, correlation_id=None):
    """Destroy the current session and publish a safe logout event."""
    session = current_auth_session(request) or {}
    request.session.flush()
    if session.get("user_id"):
        emit_event(
            "auth.logout",
            {"message": "User logged out"},
            correlation_id=correlation_id,
            user_id=session["user_id"],
        )


def get_profile(request):
    return public_user(require_authenticated_user(request))


def update_profile(request, payload, *, correlation_id=None):
    """Update profile fields, travel preferences, and an optional password."""
    user = require_authenticated_user(request)
    username = validate_username(payload.get("username", user.username))
    email = normalize_email(payload.get("email", user.email))
    password = validate_password(payload.get("password"), required=False)
    preferences = str(
        payload.get("travel_preferences", payload.get("preferences", ""))
    ).strip()

    duplicate = UserAccount.objects.filter(email=email).exclude(user_id=user.user_id)
    if duplicate.exists():
        raise ConflictError("An account with that email already exists.")

    user.username = username
    user.email = email
    user.travel_preferences = preferences
    update_fields = ["username", "email", "travel_preferences", "updated_at"]
    if password:
        user.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        update_fields.append("password_hash")
    user.save(update_fields=update_fields)
    store_auth_session(request, public_user(user))

    emit_event(
        "profile.updated",
        {"message": "Profile updated"},
        correlation_id=correlation_id,
        user_id=user.user_id,
    )
    if password:
        emit_event(
            "auth.password.changed",
            {"message": "Password changed"},
            correlation_id=correlation_id,
            user_id=user.user_id,
        )
    return public_user(user)

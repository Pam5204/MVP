"""Thin HTTP controllers for the DreamEscapes public API."""

from functools import wraps
from uuid import uuid4

from rest_framework.decorators import api_view
from rest_framework.response import Response

from backend.models import UserAccount
from backend.services.admin_service import (
    list_audit_logs,
    list_cached_destinations,
    list_users,
    review_destination,
    update_user_role,
    update_user_status,
)
from backend.services.auth_service import (
    authenticate_user,
    clear_auth_session,
    current_auth_session,
    get_profile,
    register_user,
    require_authenticated_user,
    store_auth_session,
    update_profile,
)
from backend.services.bucket_list_service import (
    delete_bucket_list_item,
    list_bucket_list_items,
    save_bucket_list_item,
    update_bucket_list_item,
)
from backend.services.destination_service import (
    get_destination_details,
    recent_searches,
    search_destinations,
)
from backend.services.errors import ServiceError


def _correlation_id(request):
    """Use an inbound trace ID when present, otherwise create one."""
    return (
        request.headers.get("X-Correlation-ID")
        or request.headers.get("X-Request-ID")
        or str(uuid4())
    )


def _service_errors(view):
    """Convert service exceptions into one safe API error contract."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ServiceError as error:
            return Response(
                {
                    "success": False,
                    "error": error.message,
                    "error_code": error.code,
                },
                status=error.status_code,
            )
        except TimeoutError:
            return Response(
                {
                    "success": False,
                    "error": "A required service did not respond in time.",
                    "error_code": "SERVICE_TIMEOUT",
                },
                status=504,
            )
        except Exception:
            return Response(
                {
                    "success": False,
                    "error": "The request could not be completed.",
                    "error_code": "INTERNAL_ERROR",
                },
                status=500,
            )

    return wrapped


def _optional_user(request):
    """Load an enabled user for optional search-history ownership."""
    session = current_auth_session(request) or {}
    if not session.get("user_id"):
        return None
    return UserAccount.objects.filter(
        user_id=session["user_id"],
        account_status=UserAccount.STATUS_ENABLED,
    ).first()


@api_view(["GET"])
def health(request):
    return Response({"success": True, "message": "DreamEscapes API is ready."})


@api_view(["POST"])
@_service_errors
def register(request):
    user = register_user(
        request.data.get("username"),
        request.data.get("email"),
        request.data.get("password"),
        correlation_id=_correlation_id(request),
    )
    return Response(
        {
            "success": True,
            "message": "Registration successful. You can now log in.",
            "user": user,
        },
        status=201,
    )


@api_view(["POST"])
@_service_errors
def login(request):
    user = authenticate_user(
        request.data.get("email"),
        request.data.get("password"),
        correlation_id=_correlation_id(request),
    )
    store_auth_session(request, user)
    return Response(
        {
            "success": True,
            "message": "Login successful.",
            "user": user,
        }
    )


@api_view(["POST"])
@_service_errors
def logout(request):
    clear_auth_session(request, correlation_id=_correlation_id(request))
    return Response({"success": True, "message": "Logout successful."})


@api_view(["GET", "PUT"])
@_service_errors
def profile(request):
    if request.method == "GET":
        user = get_profile(request)
    else:
        user = update_profile(
            request,
            request.data,
            correlation_id=_correlation_id(request),
        )
    return Response({"success": True, "profile": user})


@api_view(["GET"])
@_service_errors
def destination_search(request):
    result = search_destinations(
        request.query_params,
        user=_optional_user(request),
        correlation_id=_correlation_id(request),
    )
    message = (
        "No destinations matched your search."
        if result["count"] == 0
        else "Destination search completed."
    )
    return Response({"success": True, "message": message, **result})


@api_view(["GET"])
@_service_errors
def destination_detail(request, place_id):
    result = get_destination_details(
        place_id,
        user=_optional_user(request),
        correlation_id=_correlation_id(request),
    )
    return Response(
        {"success": True, "message": "Destination details loaded.", **result}
    )


@api_view(["GET"])
@_service_errors
def search_history(request):
    user = require_authenticated_user(request)
    return Response(
        {
            "success": True,
            "search_history": recent_searches(user),
        }
    )


@api_view(["GET", "POST"])
@_service_errors
def bucket_list_collection(request):
    user = require_authenticated_user(request)
    correlation_id = _correlation_id(request)
    if request.method == "GET":
        items = list_bucket_list_items(user)
        return Response(
            {"success": True, "count": len(items), "bucket_list": items}
        )
    item = save_bucket_list_item(
        user,
        request.data,
        correlation_id=correlation_id,
    )
    return Response(
        {
            "success": True,
            "message": "Destination saved successfully.",
            "bucket_list_item": item,
        },
        status=201,
    )


@api_view(["PUT", "PATCH", "DELETE"])
@_service_errors
def bucket_list_item(request, bucket_item_id):
    user = require_authenticated_user(request)
    correlation_id = _correlation_id(request)
    if request.method in {"PUT", "PATCH"}:
        item = update_bucket_list_item(
            user,
            bucket_item_id,
            request.data,
            correlation_id=correlation_id,
        )
        return Response(
            {
                "success": True,
                "message": "Bucket-list item updated successfully.",
                "bucket_list_item": item,
            }
        )
    result = delete_bucket_list_item(
        user,
        bucket_item_id,
        correlation_id=correlation_id,
    )
    return Response(
        {
            "success": True,
            "message": "Bucket-list item deleted successfully.",
            "deleted": result,
        }
    )


@api_view(["GET"])
@_service_errors
def admin_users(request):
    users = list_users(request, correlation_id=_correlation_id(request))
    return Response({"success": True, "count": len(users), "users": users})


@api_view(["PUT"])
@_service_errors
def admin_user_role(request, user_id):
    user = update_user_role(
        request,
        user_id,
        request.data.get("role"),
        correlation_id=_correlation_id(request),
    )
    return Response(
        {"success": True, "message": "User role updated.", "user": user}
    )


@api_view(["PUT"])
@_service_errors
def admin_user_status(request, user_id):
    user = update_user_status(
        request,
        user_id,
        request.data.get("account_status", request.data.get("status")),
        correlation_id=_correlation_id(request),
    )
    return Response(
        {"success": True, "message": "User account status updated.", "user": user}
    )


@api_view(["GET"])
@_service_errors
def admin_destinations(request):
    destinations = list_cached_destinations(
        request,
        correlation_id=_correlation_id(request),
    )
    return Response(
        {
            "success": True,
            "count": len(destinations),
            "destinations": destinations,
        }
    )


@api_view(["POST"])
@_service_errors
def admin_destination_review(request, cache_id):
    result = review_destination(
        request,
        cache_id,
        correlation_id=_correlation_id(request),
    )
    return Response(
        {
            "success": True,
            "message": "Destination review recorded.",
            "destination": result,
        }
    )


@api_view(["GET"])
@_service_errors
def admin_audit_logs(request):
    records = list_audit_logs(request, correlation_id=_correlation_id(request))
    return Response(
        {"success": True, "count": len(records), "audit_logs": records}
    )

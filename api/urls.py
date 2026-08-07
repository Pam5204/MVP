"""Public DreamEscapes HTTP route contract."""

from django.urls import path

from api.views import (
    admin_audit_logs,
    admin_destination_review,
    admin_destinations,
    admin_user_role,
    admin_user_status,
    admin_users,
    bucket_list_collection,
    bucket_list_item,
    community_post_item,
    community_post_moderation,
    community_posts,
    destination_detail,
    destination_reviews,
    destination_search,
    health,
    login,
    logout,
    profile,
    register,
    search_history,
)

urlpatterns = [
    path("health", health, name="api-health"),
    path("register", register, name="register"),
    path("login", login, name="login"),
    path("logout", logout, name="logout"),
    path("profile", profile, name="profile"),
    path("destinations/search", destination_search, name="destination-search"),
    path(
        "destinations/search-history",
        search_history,
        name="destination-search-history",
    ),
    path(
        "destinations/<str:place_id>",
        destination_detail,
        name="destination-detail",
    ),
    path(
        "destinations/<str:place_id>/reviews",
        destination_reviews,
        name="destination-reviews",
    ),
    path("bucket-list", bucket_list_collection, name="bucket-list"),
    path(
        "bucket-list/<int:bucket_item_id>",
        bucket_list_item,
        name="bucket-list-item",
    ),
    path("community/posts", community_posts, name="community-posts"),
    path(
        "community/posts/<int:post_id>",
        community_post_item,
        name="community-post-item",
    ),
    path(
        "community/posts/<int:post_id>/moderation",
        community_post_moderation,
        name="community-post-moderation",
    ),
    path("admin/users", admin_users, name="admin-users"),
    path(
        "admin/users/<int:user_id>/role",
        admin_user_role,
        name="admin-user-role",
    ),
    path(
        "admin/users/<int:user_id>/status",
        admin_user_status,
        name="admin-user-status",
    ),
    path("admin/destinations", admin_destinations, name="admin-destinations"),
    path(
        "admin/destinations/<int:cache_id>/review",
        admin_destination_review,
        name="admin-destination-review",
    ),
    path("admin/audit-logs", admin_audit_logs, name="admin-audit-logs"),
]

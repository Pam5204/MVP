"""Django admin registrations for backend-owned persistence models."""

from django.contrib import admin

from backend.models import (
    AdminAuditLog,
    BucketListDestination,
    CommunityPost,
    DestinationCache,
    DestinationReference,
    DestinationReview,
    SearchHistory,
    UserAccount,
)


@admin.register(UserAccount)
class UserAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "username", "role", "account_status", "created_at")
    search_fields = ("email", "username")
    list_filter = ("role", "account_status")
    exclude = ("password_hash",)


admin.site.register(BucketListDestination)
admin.site.register(DestinationCache)
admin.site.register(DestinationReference)
admin.site.register(DestinationReview)
admin.site.register(CommunityPost)
admin.site.register(SearchHistory)
admin.site.register(AdminAuditLog)

"""Persistence models for the DreamEscapes application backend.

The field and table names intentionally match ``db/DreamEscapes.sql`` so the
Django and the DB-role consumer share one MySQL-only persistence contract.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class UserAccount(models.Model):
    """One registered DreamEscapes user or administrator."""

    ROLE_USER = "user"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = ((ROLE_USER, "User"), (ROLE_ADMIN, "Admin"))

    STATUS_ENABLED = "enabled"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = (
        (STATUS_ENABLED, "Enabled"),
        (STATUS_DISABLED, "Disabled"),
    )

    user_id = models.BigAutoField(primary_key=True)
    username = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_USER)
    travel_preferences = models.TextField(blank=True)
    account_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ENABLED,
    )
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["role"], name="idx_users_role"),
            models.Index(fields=["account_status"], name="idx_users_status"),
        ]

    def __str__(self):
        return self.email


class BucketListDestination(models.Model):
    """A destination saved by one owning user."""

    bucket_item_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="bucket_list_destinations",
        db_column="user_id",
    )
    destination_name = models.CharField(max_length=255)
    city = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=150, blank=True)
    categories = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    place_id = models.CharField(max_length=255)
    travel_type_label = models.CharField(max_length=100, blank=True)
    saved_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bucket_list_destinations"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "place_id"],
                name="uq_bucket_user_place",
            )
        ]
        indexes = [
            models.Index(fields=["user"], name="idx_bucket_user"),
            models.Index(fields=["place_id"], name="idx_bucket_place"),
            models.Index(fields=["country"], name="idx_bucket_country"),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.destination_name}"


class DestinationCache(models.Model):
    """Normalized Geoapify search or detail data with a 24-hour expiry."""

    cache_id = models.BigAutoField(primary_key=True)
    cache_key = models.CharField(max_length=128, unique=True)
    place_id = models.CharField(max_length=255, blank=True)
    normalized_query = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=150, blank=True)
    categories = models.CharField(max_length=500, blank=True)
    attraction_type = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )
    destination_name = models.CharField(max_length=255, blank=True)
    destination_description = models.TextField(blank=True)
    attractions = models.JSONField(default=list)
    nearby_attractions = models.JSONField(default=list)
    formatted_address = models.TextField(blank=True)
    payload = models.JSONField(default=dict)
    raw_api_response = models.JSONField(default=dict)
    source_api = models.CharField(max_length=50, default="Geoapify")
    cached_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "destination_cache"
        indexes = [
            models.Index(fields=["place_id"], name="idx_cache_place"),
            models.Index(fields=["normalized_query"], name="idx_cache_query"),
            models.Index(fields=["country"], name="idx_cache_country"),
            models.Index(fields=["categories"], name="idx_cache_categories"),
            models.Index(fields=["expires_at"], name="idx_cache_expires"),
        ]

    def __str__(self):
        return self.cache_key


class SearchHistory(models.Model):
    """One authenticated user's normalized destination search."""

    search_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="search_history",
        db_column="user_id",
        null=True,
        blank=True,
    )
    query = models.CharField(max_length=255)
    country_filter = models.CharField(max_length=150, blank=True)
    category_filter = models.CharField(max_length=255, blank=True)
    attraction_type_filter = models.CharField(max_length=100, blank=True)
    place_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "search_history"
        indexes = [
            models.Index(fields=["user"], name="idx_history_user"),
            models.Index(fields=["created_at"], name="idx_history_created"),
        ]


class AdminAuditLog(models.Model):
    """A durable record of an administrator action or access decision."""

    audit_id = models.BigAutoField(primary_key=True)
    admin_user = models.ForeignKey(
        UserAccount,
        on_delete=models.PROTECT,
        related_name="admin_audit_logs",
        db_column="admin_user_id",
    )
    action_type = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=50, default="success")

    class Meta:
        db_table = "admin_audit_logs"
        indexes = [
            models.Index(fields=["admin_user"], name="idx_audit_admin"),
            models.Index(fields=["created_at"], name="idx_audit_created"),
        ]

    def __str__(self):
        return f"{self.action_type}: {self.target_type} {self.target_id}"


class DestinationReference(models.Model):
    """A stable destination identity shared by persisted user reviews.

    Geoapify search/cache rows are intentionally transient and may contain an
    entire result set.  This small record gives reviews a durable relational
    target keyed by Geoapify's place ID without coupling them to cache expiry.
    """

    destination_id = models.BigAutoField(primary_key=True)
    place_id = models.CharField(max_length=255, unique=True)
    destination_name = models.CharField(max_length=255)
    city = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=150, blank=True)
    formatted_address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "destinations"
        indexes = [
            models.Index(fields=["destination_name"], name="idx_destination_name"),
            models.Index(fields=["country"], name="idx_destination_country"),
        ]

    def __str__(self):
        return self.destination_name


class DestinationReview(models.Model):
    """An authenticated user's persisted comment and 1-5 destination rating."""

    review_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="destination_reviews",
        db_column="user_id",
    )
    destination = models.ForeignKey(
        DestinationReference,
        on_delete=models.CASCADE,
        related_name="reviews",
        db_column="destination_id",
    )
    comment = models.TextField()
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "destination_reviews"
        indexes = [
            models.Index(fields=["destination"], name="idx_review_destination"),
            models.Index(fields=["user"], name="idx_review_user"),
            models.Index(fields=["created_at"], name="idx_review_created"),
        ]

    def __str__(self):
        return f"{self.destination}: {self.rating}/5 by {self.user}"


class CommunityPost(models.Model):
    """A persisted travel experience or question on the community page."""

    TYPE_EXPERIENCE = "experience"
    TYPE_QUESTION = "question"
    TYPE_CHOICES = (
        (TYPE_EXPERIENCE, "Travel experience"),
        (TYPE_QUESTION, "Question"),
    )

    STATUS_VISIBLE = "visible"
    STATUS_HIDDEN = "hidden"
    STATUS_CHOICES = (
        (STATUS_VISIBLE, "Visible"),
        (STATUS_HIDDEN, "Hidden"),
    )

    post_id = models.BigAutoField(primary_key=True)
    author = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="community_posts",
        db_column="author_user_id",
    )
    post_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=160)
    body = models.TextField()
    destination_name = models.CharField(max_length=255, blank=True)
    picture_url = models.URLField(max_length=1000, blank=True)
    moderation_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_VISIBLE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "community_posts"
        indexes = [
            models.Index(fields=["author"], name="idx_community_author"),
            models.Index(fields=["post_type"], name="idx_community_type"),
            models.Index(fields=["moderation_status"], name="idx_community_status"),
            models.Index(fields=["created_at"], name="idx_community_created"),
        ]

    def __str__(self):
        return self.title

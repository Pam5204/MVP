"""Initial DreamEscapes persistence schema."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="UserAccount",
            fields=[
                ("user_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("username", models.CharField(max_length=100)),
                ("email", models.EmailField(max_length=255, unique=True)),
                ("password_hash", models.CharField(max_length=255)),
                (
                    "role",
                    models.CharField(
                        choices=[("user", "User"), ("admin", "Admin")],
                        default="user",
                        max_length=20,
                    ),
                ),
                ("travel_preferences", models.TextField(blank=True)),
                (
                    "account_status",
                    models.CharField(
                        choices=[("enabled", "Enabled"), ("disabled", "Disabled")],
                        default="enabled",
                        max_length=20,
                    ),
                ),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "users",
                "indexes": [
                    models.Index(fields=["role"], name="idx_users_role"),
                    models.Index(fields=["account_status"], name="idx_users_status"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DestinationCache",
            fields=[
                ("cache_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("cache_key", models.CharField(max_length=128, unique=True)),
                ("place_id", models.CharField(blank=True, max_length=255)),
                ("normalized_query", models.CharField(blank=True, max_length=255)),
                ("country", models.CharField(blank=True, max_length=150)),
                ("categories", models.CharField(blank=True, max_length=500)),
                ("attraction_type", models.CharField(blank=True, max_length=100)),
                (
                    "latitude",
                    models.DecimalField(
                        blank=True, decimal_places=7, max_digits=10, null=True
                    ),
                ),
                (
                    "longitude",
                    models.DecimalField(
                        blank=True, decimal_places=7, max_digits=10, null=True
                    ),
                ),
                ("destination_name", models.CharField(blank=True, max_length=255)),
                ("destination_description", models.TextField(blank=True)),
                ("attractions", models.JSONField(default=list)),
                ("nearby_attractions", models.JSONField(default=list)),
                ("formatted_address", models.TextField(blank=True)),
                ("payload", models.JSONField(default=dict)),
                ("raw_api_response", models.JSONField(default=dict)),
                ("source_api", models.CharField(default="Geoapify", max_length=50)),
                ("cached_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "destination_cache",
                "indexes": [
                    models.Index(fields=["place_id"], name="idx_cache_place"),
                    models.Index(fields=["normalized_query"], name="idx_cache_query"),
                    models.Index(fields=["country"], name="idx_cache_country"),
                    models.Index(fields=["categories"], name="idx_cache_categories"),
                    models.Index(fields=["expires_at"], name="idx_cache_expires"),
                ],
            },
        ),
        migrations.CreateModel(
            name="BucketListDestination",
            fields=[
                ("bucket_item_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("destination_name", models.CharField(max_length=255)),
                ("city", models.CharField(blank=True, max_length=150)),
                ("country", models.CharField(blank=True, max_length=150)),
                ("categories", models.TextField(blank=True)),
                ("latitude", models.DecimalField(decimal_places=7, max_digits=10)),
                ("longitude", models.DecimalField(decimal_places=7, max_digits=10)),
                ("place_id", models.CharField(max_length=255)),
                ("travel_type_label", models.CharField(blank=True, max_length=100)),
                ("saved_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bucket_list_destinations",
                        to="backend.useraccount",
                    ),
                ),
            ],
            options={
                "db_table": "bucket_list_destinations",
                "indexes": [
                    models.Index(fields=["user"], name="idx_bucket_user"),
                    models.Index(fields=["place_id"], name="idx_bucket_place"),
                    models.Index(fields=["country"], name="idx_bucket_country"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "place_id"), name="uq_bucket_user_place"
                    )
                ],
            },
        ),
        # MySQL requires a prefix length when indexing a TEXT column. The
        # project is MySQL-only, so create the same 191-character prefix index
        # used by db/DreamEscapes.sql instead of Django's generic full index.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX idx_bucket_categories "
                "ON bucket_list_destinations (categories(191))"
            ),
            reverse_sql=(
                "DROP INDEX idx_bucket_categories "
                "ON bucket_list_destinations"
            ),
        ),
        migrations.CreateModel(
            name="SearchHistory",
            fields=[
                ("search_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("query", models.CharField(max_length=255)),
                ("country_filter", models.CharField(blank=True, max_length=150)),
                ("category_filter", models.CharField(blank=True, max_length=255)),
                (
                    "attraction_type_filter",
                    models.CharField(blank=True, max_length=100),
                ),
                ("place_id", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        db_column="user_id",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="search_history",
                        to="backend.useraccount",
                    ),
                ),
            ],
            options={
                "db_table": "search_history",
                "indexes": [
                    models.Index(fields=["user"], name="idx_history_user"),
                    models.Index(fields=["created_at"], name="idx_history_created"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AdminAuditLog",
            fields=[
                ("audit_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("action_type", models.CharField(max_length=100)),
                ("target_type", models.CharField(max_length=100)),
                ("target_id", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(default="success", max_length=50)),
                (
                    "admin_user",
                    models.ForeignKey(
                        db_column="admin_user_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="admin_audit_logs",
                        to="backend.useraccount",
                    ),
                ),
            ],
            options={
                "db_table": "admin_audit_logs",
                "indexes": [
                    models.Index(fields=["admin_user"], name="idx_audit_admin"),
                    models.Index(fields=["created_at"], name="idx_audit_created"),
                ],
            },
        ),
    ]

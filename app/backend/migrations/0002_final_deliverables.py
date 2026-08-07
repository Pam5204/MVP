"""Required final-deliverable review and community persistence.

The project is MySQL-only and setup_mysql.sh loads db/DreamEscapes.sql before
running migrations. CREATE TABLE IF NOT EXISTS keeps a new installation and an
upgrade of an existing database on the same repeatable path, while the state
operations keep Django's model graph accurate.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


CREATE_DESTINATIONS = """
CREATE TABLE IF NOT EXISTS `destinations` (
  `destination_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `place_id` VARCHAR(255) NOT NULL,
  `destination_name` VARCHAR(255) NOT NULL,
  `city` VARCHAR(150) NOT NULL DEFAULT '',
  `country` VARCHAR(150) NOT NULL DEFAULT '',
  `formatted_address` TEXT NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`destination_id`),
  UNIQUE KEY `uq_destination_place` (`place_id`),
  KEY `idx_destination_name` (`destination_name`),
  KEY `idx_destination_country` (`country`)
) ENGINE=InnoDB
"""

CREATE_REVIEWS = """
CREATE TABLE IF NOT EXISTS `destination_reviews` (
  `review_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `destination_id` BIGINT UNSIGNED NOT NULL,
  `comment` TEXT NOT NULL,
  `rating` SMALLINT UNSIGNED NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`review_id`),
  KEY `idx_review_destination` (`destination_id`),
  KEY `idx_review_user` (`user_id`),
  KEY `idx_review_created` (`created_at`),
  CONSTRAINT `chk_review_rating` CHECK (`rating` BETWEEN 1 AND 5),
  CONSTRAINT `fk_review_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_review_destination`
    FOREIGN KEY (`destination_id`) REFERENCES `destinations` (`destination_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB
"""

CREATE_COMMUNITY_POSTS = """
CREATE TABLE IF NOT EXISTS `community_posts` (
  `post_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `author_user_id` BIGINT UNSIGNED NOT NULL,
  `post_type` ENUM('experience', 'question') NOT NULL,
  `title` VARCHAR(160) NOT NULL,
  `body` TEXT NOT NULL,
  `destination_name` VARCHAR(255) NOT NULL DEFAULT '',
  `picture_url` VARCHAR(1000) NOT NULL DEFAULT '',
  `moderation_status` ENUM('visible', 'hidden') NOT NULL DEFAULT 'visible',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`post_id`),
  KEY `idx_community_author` (`author_user_id`),
  KEY `idx_community_type` (`post_type`),
  KEY `idx_community_status` (`moderation_status`),
  KEY `idx_community_created` (`created_at`),
  CONSTRAINT `fk_community_author`
    FOREIGN KEY (`author_user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB
"""


class Migration(migrations.Migration):
    dependencies = [("backend", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(CREATE_DESTINATIONS, "DROP TABLE IF EXISTS `destinations`")
            ],
            state_operations=[
                migrations.CreateModel(
                    name="DestinationReference",
                    fields=[
                        (
                            "destination_id",
                            models.BigAutoField(primary_key=True, serialize=False),
                        ),
                        ("place_id", models.CharField(max_length=255, unique=True)),
                        ("destination_name", models.CharField(max_length=255)),
                        ("city", models.CharField(blank=True, max_length=150)),
                        ("country", models.CharField(blank=True, max_length=150)),
                        ("formatted_address", models.TextField(blank=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "destinations",
                        "indexes": [
                            models.Index(
                                fields=["destination_name"],
                                name="idx_destination_name",
                            ),
                            models.Index(
                                fields=["country"], name="idx_destination_country"
                            ),
                        ],
                    },
                )
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    CREATE_REVIEWS, "DROP TABLE IF EXISTS `destination_reviews`"
                )
            ],
            state_operations=[
                migrations.CreateModel(
                    name="DestinationReview",
                    fields=[
                        (
                            "review_id",
                            models.BigAutoField(primary_key=True, serialize=False),
                        ),
                        ("comment", models.TextField()),
                        (
                            "rating",
                            models.PositiveSmallIntegerField(
                                validators=[
                                    django.core.validators.MinValueValidator(1),
                                    django.core.validators.MaxValueValidator(5),
                                ]
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "destination",
                            models.ForeignKey(
                                db_column="destination_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="reviews",
                                to="backend.destinationreference",
                            ),
                        ),
                        (
                            "user",
                            models.ForeignKey(
                                db_column="user_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="destination_reviews",
                                to="backend.useraccount",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "destination_reviews",
                        "indexes": [
                            models.Index(
                                fields=["destination"], name="idx_review_destination"
                            ),
                            models.Index(fields=["user"], name="idx_review_user"),
                            models.Index(
                                fields=["created_at"], name="idx_review_created"
                            ),
                        ],
                    },
                )
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    CREATE_COMMUNITY_POSTS,
                    "DROP TABLE IF EXISTS `community_posts`",
                )
            ],
            state_operations=[
                migrations.CreateModel(
                    name="CommunityPost",
                    fields=[
                        (
                            "post_id",
                            models.BigAutoField(primary_key=True, serialize=False),
                        ),
                        (
                            "post_type",
                            models.CharField(
                                choices=[
                                    ("experience", "Travel experience"),
                                    ("question", "Question"),
                                ],
                                max_length=20,
                            ),
                        ),
                        ("title", models.CharField(max_length=160)),
                        ("body", models.TextField()),
                        (
                            "destination_name",
                            models.CharField(blank=True, max_length=255),
                        ),
                        ("picture_url", models.URLField(blank=True, max_length=1000)),
                        (
                            "moderation_status",
                            models.CharField(
                                choices=[
                                    ("visible", "Visible"),
                                    ("hidden", "Hidden"),
                                ],
                                default="visible",
                                max_length=20,
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "author",
                            models.ForeignKey(
                                db_column="author_user_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="community_posts",
                                to="backend.useraccount",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "community_posts",
                        "indexes": [
                            models.Index(
                                fields=["author"], name="idx_community_author"
                            ),
                            models.Index(
                                fields=["post_type"], name="idx_community_type"
                            ),
                            models.Index(
                                fields=["moderation_status"],
                                name="idx_community_status",
                            ),
                            models.Index(
                                fields=["created_at"], name="idx_community_created"
                            ),
                        ],
                    },
                )
            ],
        ),
    ]

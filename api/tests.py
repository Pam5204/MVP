"""End-to-end API contract tests for the MVP checklist."""

from datetime import timedelta
from unittest.mock import patch

import bcrypt
from django.test import TestCase
from django.utils import timezone

from backend.models import (
    AdminAuditLog,
    BucketListDestination,
    DestinationCache,
    SearchHistory,
    UserAccount,
)
from backend.services.geoapify_service import GeoapifyServiceError


def _password_hash(password="StrongPass123!"):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode(
        "utf-8"
    )


def _search_upstream(place_id="place-museum"):
    destination = {
        "place_id": place_id,
        "name": "Newark Museum of Art",
        "city": "Newark",
        "state": "New Jersey",
        "country": "United States",
        "country_code": "us",
        "categories": ["entertainment.museum"],
        "category": "entertainment.museum",
        "formatted_address": "49 Washington St, Newark, NJ",
        "address_line1": "49 Washington St",
        "address_line2": "Newark, NJ",
        "latitude": 40.7429,
        "longitude": -74.1712,
        "distance": 100,
        "description": "Museum destination",
    }
    return {
        "location": {
            **destination,
            "place_id": "place-newark",
            "name": "Newark",
        },
        "results": [destination],
        "count": 1,
        "raw_api_response": {"places": {"features": []}},
    }


def _detail_upstream(place_id="place-museum"):
    nearby = [
        {
            "place_id": "place-park",
            "name": "Military Park",
            "city": "Newark",
            "country": "United States",
            "categories": ["leisure.park"],
            "formatted_address": "Military Park, Newark, NJ",
            "latitude": 40.7407,
            "longitude": -74.1699,
            "distance": 250,
            "description": "Nearby park",
        }
    ]
    return {
        "destination": {
            "place_id": place_id,
            "name": "Newark Museum of Art",
            "city": "Newark",
            "country": "United States",
            "categories": ["entertainment.museum"],
            "formatted_address": "49 Washington St, Newark, NJ",
            "latitude": 40.7429,
            "longitude": -74.1712,
            "distance": None,
            "description": "Museum destination",
            "nearby_attractions": nearby,
            "points_of_interest": nearby,
        },
        "raw_api_response": {"details": {"features": []}},
    }


class ApiTestBase(TestCase):
    password = "StrongPass123!"

    @classmethod
    def setUpClass(cls):
        """Replace the live MQ round trip with a DB-consumer simulation."""
        super().setUpClass()
        cls._auth_command_patcher = patch(
            "backend.services.auth_service._request_auth_command",
            side_effect=cls._simulate_auth_consumer,
        )
        cls._auth_command_patcher.start()
        cls.addClassCleanup(cls._auth_command_patcher.stop)

    @classmethod
    def _simulate_auth_consumer(cls, message):
        """Mirror safe register/login results while API tests use test MySQL."""
        payload = message["payload"]
        if message["type"] == "auth.register.request":
            if UserAccount.objects.filter(email=payload["email"]).exists():
                return {
                    "success": False,
                    "error": "An account with that email already exists.",
                    "correlation_id": message["correlation_id"],
                }
            user = UserAccount.objects.create(
                username=payload["username"],
                email=payload["email"],
                password_hash=_password_hash(payload["password"]),
            )
            return {
                "success": True,
                "correlation_id": message["correlation_id"],
                "payload": {
                    "user_id": user.user_id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "account_status": user.account_status,
                    "travel_preferences": user.travel_preferences,
                },
            }

        user = UserAccount.objects.filter(email=payload["email"]).first()
        password_matches = False
        if user:
            try:
                password_matches = bcrypt.checkpw(
                    payload["password"].encode("utf-8"),
                    user.password_hash.encode("utf-8"),
                )
            except ValueError:
                password_matches = False
        if (
            not user
            or not password_matches
            or user.account_status != UserAccount.STATUS_ENABLED
        ):
            return {
                "success": False,
                "error": "Invalid email or password.",
                "correlation_id": message["correlation_id"],
            }
        return {
            "success": True,
            "correlation_id": message["correlation_id"],
            "payload": {
                "user_id": user.user_id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "account_status": user.account_status,
                "travel_preferences": user.travel_preferences,
            },
        }

    def create_user(
        self,
        *,
        email="traveler@example.com",
        username="Traveler",
        role=UserAccount.ROLE_USER,
        status=UserAccount.STATUS_ENABLED,
    ):
        return UserAccount.objects.create(
            username=username,
            email=email,
            password_hash=_password_hash(self.password),
            role=role,
            account_status=status,
        )

    def login(self, email="traveler@example.com", password=None):
        return self.client.post(
            "/api/login",
            {"email": email, "password": password or self.password},
            content_type="application/json",
        )


class AuthenticationProfileApiTests(ApiTestBase):
    def test_register_login_profile_update_and_logout(self):
        register = self.client.post(
            "/api/register",
            {
                "username": "New Traveler",
                "email": "NEW@example.com",
                "password": self.password,
            },
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)
        body = register.json()
        self.assertEqual(body["user"]["email"], "new@example.com")
        self.assertNotIn("password", str(body).lower())

        login = self.login("new@example.com")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user"]["role"], "user")

        profile = self.client.get("/api/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["profile"]["username"], "New Traveler")

        update = self.client.put(
            "/api/profile",
            {
                "username": "Updated Traveler",
                "email": "updated@example.com",
                "travel_preferences": "Museums and parks",
                "password": "",
            },
            content_type="application/json",
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(
            update.json()["profile"]["travel_preferences"], "Museums and parks"
        )

        logout = self.client.post("/api/logout", {}, content_type="application/json")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").status_code, 401)

    def test_registration_validation_and_duplicate_email(self):
        incomplete = self.client.post(
            "/api/register",
            {"username": "", "email": "", "password": ""},
            content_type="application/json",
        )
        self.assertEqual(incomplete.status_code, 400)
        self.create_user()
        duplicate = self.client.post(
            "/api/register",
            {
                "username": "Another Traveler",
                "email": "TRAVELER@example.com",
                "password": self.password,
            },
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_login_errors_are_generic_and_disabled_accounts_are_blocked(self):
        self.create_user()
        wrong = self.login(password="WrongPass123!")
        missing = self.login("missing@example.com")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.json()["error"], missing.json()["error"])

        user = UserAccount.objects.get(email="traveler@example.com")
        user.account_status = UserAccount.STATUS_DISABLED
        user.save(update_fields=["account_status"])
        self.assertEqual(self.login().status_code, 401)

    def test_profile_requires_authentication(self):
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        self.assertEqual(
            self.client.put(
                "/api/profile",
                {"username": "No Session", "email": "none@example.com"},
                content_type="application/json",
            ).status_code,
            401,
        )


class DestinationApiTests(ApiTestBase):
    def setUp(self):
        self.user = self.create_user()
        self.login()

    @patch("backend.services.destination_service.geoapify_search_destinations")
    def test_search_cache_miss_then_fresh_hit_and_history(self, geo_search):
        geo_search.return_value = _search_upstream()
        first = self.client.get(
            "/api/destinations/search",
            {
                "name": "Newark",
                "country": "US",
                "category": "culture",
                "attraction_type": "museum",
            },
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["cache_status"], "refreshed")
        self.assertEqual(first.json()["results"][0]["name"], "Newark Museum of Art")

        second = self.client.get(
            "/api/destinations/search",
            {
                "name": "Newark",
                "country": "US",
                "category": "culture",
                "attraction_type": "museum",
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["cache_status"], "fresh")
        self.assertEqual(geo_search.call_count, 1)
        self.assertEqual(SearchHistory.objects.filter(user=self.user).count(), 2)

    @patch("backend.services.destination_service.geoapify_search_destinations")
    def test_stale_search_cache_is_used_when_geoapify_fails(self, geo_search):
        geo_search.return_value = _search_upstream()
        self.client.get("/api/destinations/search", {"name": "Newark"})
        cache = DestinationCache.objects.get(normalized_query="newark")
        cache.expires_at = timezone.now() - timedelta(minutes=1)
        cache.save(update_fields=["expires_at"])
        geo_search.side_effect = GeoapifyServiceError("offline")

        response = self.client.get("/api/destinations/search", {"name": "Newark"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cache_status"], "stale")
        self.assertTrue(response.json()["cache_warning"])

    @patch("backend.services.destination_service.geoapify_search_destinations")
    def test_search_without_cache_returns_friendly_failure(self, geo_search):
        geo_search.side_effect = GeoapifyServiceError("offline")
        response = self.client.get("/api/destinations/search", {"name": "Nowhere"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"],
            "Destination information is temporarily unavailable.",
        )

    @patch("backend.services.destination_service.geoapify_destination_details")
    def test_destination_details_include_nearby_and_cache(self, geo_details):
        geo_details.return_value = _detail_upstream()
        first = self.client.get("/api/destinations/place-museum")
        second = self.client.get("/api/destinations/place-museum")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["cache_status"], "refreshed")
        self.assertEqual(
            first.json()["destination"]["nearby_attractions"][0]["name"],
            "Military Park",
        )
        self.assertEqual(second.json()["cache_status"], "fresh")
        self.assertEqual(geo_details.call_count, 1)

    def test_search_parameters_are_validated(self):
        self.assertEqual(self.client.get("/api/destinations/search").status_code, 400)
        self.assertEqual(
            self.client.get(
                "/api/destinations/search", {"name": "Newark", "limit": 100}
            ).status_code,
            400,
        )


class BucketListApiTests(ApiTestBase):
    def setUp(self):
        self.user = self.create_user()
        self.other = self.create_user(
            email="other@example.com",
            username="Other User",
        )
        self.login()
        self.payload = {
            "destination_name": "Newark Museum of Art",
            "city": "Newark",
            "country": "United States",
            "categories": ["culture", "museum"],
            "latitude": 40.7429,
            "longitude": -74.1712,
            "place_id": "place-museum",
            "travel_type_label": "weekend",
        }

    def test_bucket_list_crud_duplicate_and_ownership(self):
        save = self.client.post(
            "/api/bucket-list", self.payload, content_type="application/json"
        )
        self.assertEqual(save.status_code, 201)
        bucket_id = save.json()["bucket_list_item"]["bucket_item_id"]
        self.assertEqual(
            self.client.post(
                "/api/bucket-list", self.payload, content_type="application/json"
            ).status_code,
            409,
        )

        listing = self.client.get("/api/bucket-list")
        self.assertEqual(listing.json()["count"], 1)
        update = self.client.put(
            f"/api/bucket-list/{bucket_id}",
            {"categories": "museum", "travel_type_label": "dream-trip"},
            content_type="application/json",
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(
            update.json()["bucket_list_item"]["travel_type_label"], "dream-trip"
        )

        item = BucketListDestination.objects.get(bucket_item_id=bucket_id)
        item.user = self.other
        item.save(update_fields=["user"])
        self.assertEqual(
            self.client.delete(f"/api/bucket-list/{bucket_id}").status_code,
            404,
        )

    def test_bucket_delete_and_authentication(self):
        save = self.client.post(
            "/api/bucket-list", self.payload, content_type="application/json"
        )
        bucket_id = save.json()["bucket_list_item"]["bucket_item_id"]
        deleted = self.client.delete(f"/api/bucket-list/{bucket_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(
            BucketListDestination.objects.filter(bucket_item_id=bucket_id).exists()
        )
        self.client.post("/api/logout", {}, content_type="application/json")
        self.assertEqual(self.client.get("/api/bucket-list").status_code, 401)


class AdminApiTests(ApiTestBase):
    def setUp(self):
        self.standard = self.create_user()
        self.admin = self.create_user(
            email="admin@example.com",
            username="Administrator",
            role=UserAccount.ROLE_ADMIN,
        )

    def test_standard_user_is_blocked_from_all_admin_data(self):
        self.login()
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/destinations").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/audit-logs").status_code, 403)

    def test_admin_can_manage_users_review_destinations_and_read_audit(self):
        self.login("admin@example.com")
        users = self.client.get("/api/admin/users")
        self.assertEqual(users.status_code, 200)
        self.assertEqual(users.json()["count"], 2)

        role = self.client.put(
            f"/api/admin/users/{self.standard.user_id}/role",
            {"role": "admin"},
            content_type="application/json",
        )
        self.assertEqual(role.status_code, 200)
        status = self.client.put(
            f"/api/admin/users/{self.standard.user_id}/status",
            {"account_status": "disabled"},
            content_type="application/json",
        )
        self.assertEqual(status.status_code, 200)

        now = timezone.now()
        cache = DestinationCache.objects.create(
            cache_key="detail:admin-review",
            place_id="place-review",
            destination_name="Review Destination",
            attractions=[],
            nearby_attractions=[],
            payload={},
            raw_api_response={},
            cached_at=now,
            expires_at=now + timedelta(hours=24),
        )
        destinations = self.client.get("/api/admin/destinations")
        self.assertEqual(destinations.json()["count"], 1)
        review = self.client.post(
            f"/api/admin/destinations/{cache.cache_id}/review",
            {},
            content_type="application/json",
        )
        self.assertEqual(review.status_code, 200)

        audit = self.client.get("/api/admin/audit-logs")
        self.assertEqual(audit.status_code, 200)
        self.assertGreaterEqual(audit.json()["count"], 3)
        self.assertGreaterEqual(AdminAuditLog.objects.count(), 3)


class DomainEventWiringTests(ApiTestBase):
    """Prove backend actions invoke the canonical RabbitMQ event publisher."""

    def setUp(self):
        self.user = self.create_user()
        self.login()

    @patch("backend.services.auth_service.emit_event")
    def test_profile_actions_publish_safe_events(self, emit):
        self.client.put(
            "/api/profile",
            {
                "username": "Updated Event User",
                "email": self.user.email,
                "travel_preferences": "Parks",
                "password": "",
            },
            content_type="application/json",
        )
        event_types = [call.args[0] for call in emit.call_args_list]
        self.assertIn("profile.updated", event_types)

    @patch("backend.services.bucket_list_service.emit_event")
    def test_bucket_save_and_delete_publish_domain_events(self, emit):
        payload = {
            "destination_name": "Event Destination",
            "city": "Newark",
            "country": "United States",
            "categories": ["culture"],
            "latitude": 40.7357,
            "longitude": -74.1724,
            "place_id": "event-place",
        }
        saved = self.client.post(
            "/api/bucket-list", payload, content_type="application/json"
        )
        bucket_id = saved.json()["bucket_list_item"]["bucket_item_id"]
        self.client.delete(f"/api/bucket-list/{bucket_id}")
        event_types = [call.args[0] for call in emit.call_args_list]
        self.assertIn("bucketlist.destination.saved", event_types)
        self.assertIn("bucketlist.destination.deleted", event_types)
        self.assertIn("bucketlist.updated", event_types)

    @patch("backend.services.destination_service.emit_event")
    @patch("backend.services.destination_service.geoapify_search_destinations")
    def test_cache_refresh_and_api_failure_publish_events(self, geo_search, emit):
        geo_search.return_value = _search_upstream()
        self.client.get("/api/destinations/search", {"name": "Newark"})
        cache = DestinationCache.objects.get(normalized_query="newark")
        cache.expires_at = timezone.now() - timedelta(minutes=1)
        cache.save(update_fields=["expires_at"])
        geo_search.side_effect = GeoapifyServiceError("offline")
        self.client.get("/api/destinations/search", {"name": "Newark"})

        event_types = [call.args[0] for call in emit.call_args_list]
        self.assertIn("cache.refresh.requested", event_types)
        self.assertIn("cache.refresh.completed", event_types)
        self.assertIn("cache.destination.updated", event_types)
        self.assertIn("api.failure", event_types)
        self.assertIn("api.geoapify.unavailable", event_types)
        self.assertIn("cache.stale.used", event_types)

    @patch("backend.services.admin_service.emit_event")
    def test_admin_updates_publish_action_and_audit_events(self, emit):
        admin = self.create_user(
            email="event-admin@example.com",
            username="Event Admin",
            role=UserAccount.ROLE_ADMIN,
        )
        self.client.post("/api/logout", {}, content_type="application/json")
        self.login(admin.email)
        self.client.put(
            f"/api/admin/users/{self.user.user_id}/role",
            {"role": "admin"},
            content_type="application/json",
        )
        event_types = [call.args[0] for call in emit.call_args_list]
        self.assertIn("admin.user.role_changed", event_types)
        self.assertIn("admin.audit.created", event_types)

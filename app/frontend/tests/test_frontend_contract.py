"""Static frontend acceptance checks for the required MVP screens and routes."""

from pathlib import Path
import unittest

FRONTEND_DIR = Path(__file__).resolve().parents[1]
HTML = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
JAVASCRIPT = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
STYLES = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")
CONFIG = (FRONTEND_DIR / "config.js").read_text(encoding="utf-8")


class FrontendContractTests(unittest.TestCase):
    def test_required_views_and_forms_exist(self):
        for identifier in (
            "loginView",
            "registerView",
            "dashboardView",
            "detailsView",
            "bucketView",
            "communityView",
            "profileView",
            "adminView",
            "loginForm",
            "registerForm",
            "searchForm",
            "reviewForm",
            "communityPostForm",
            "communitySearchForm",
            "profileForm",
        ):
            self.assertIn(f'id="{identifier}"', HTML)

    def test_required_api_routes_are_used(self):
        for route in (
            "/api/register",
            "/api/login",
            "/api/logout",
            "/api/profile",
            "/api/destinations/search",
            "/reviews",
            "/api/bucket-list",
            "/api/community/posts",
            "/api/admin/users",
            "/api/admin/destinations",
            "/api/admin/audit-logs",
        ):
            self.assertIn(route, JAVASCRIPT)

    def test_no_demo_success_or_hardcoded_data_collections_remain(self):
        self.assertNotIn("demoMode", JAVASCRIPT)
        self.assertNotIn("const destinations = [", JAVASCRIPT)
        self.assertNotIn("const adminUsers = [", JAVASCRIPT)
        self.assertNotIn("includes(\"admin\")", JAVASCRIPT)

    def test_requests_include_session_credentials(self):
        self.assertIn('credentials: "include"', JAVASCRIPT)

    def test_four_vm_frontend_uses_the_app_origin(self):
        """Prevent direct browser calls to the separate API VM."""
        self.assertIn("window.location.origin", CONFIG)
        self.assertNotIn("127.0.0.1:8000", CONFIG)
        self.assertIn("window.location.origin", JAVASCRIPT)
        self.assertNotIn('|| "http://localhost:8000"', JAVASCRIPT)

    def test_invalid_login_is_not_treated_as_an_expired_session(self):
        self.assertIn(
            "isExpiredSessionError(error.status, error.code)",
            JAVASCRIPT,
        )

    def test_admin_save_targets_the_containing_user_row(self):
        self.assertIn(
            'button.closest(".table-row[data-user-id]")',
            JAVASCRIPT,
        )

    def test_required_final_feature_controls_are_api_backed(self):
        for required in (
            'name="rating"',
            'name="comment"',
            'name="post_type"',
            'name="picture_url"',
            'id="communityPostList"',
        ):
            self.assertIn(required, HTML)
        self.assertIn("community-moderate", JAVASCRIPT)
        self.assertIn("encodeURIComponent(state.communityQuery)", JAVASCRIPT)
        self.assertIn("community-picture", JAVASCRIPT)
        self.assertNotIn(
            'class="ghost-button admin-user-save" type="button" data-user-id=',
            JAVASCRIPT,
        )

    def test_layout_has_responsive_breakpoints_and_status_components(self):
        self.assertIn("@media (max-width: 900px)", STYLES)
        self.assertIn("@media (max-width: 520px)", STYLES)
        self.assertIn(".loading-state", STYLES)
        self.assertIn(".status-message.warning", STYLES)
        self.assertIn(".form-message.error", STYLES)


if __name__ == "__main__":
    unittest.main()

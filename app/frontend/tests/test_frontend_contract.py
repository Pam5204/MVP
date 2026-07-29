"""Static frontend acceptance checks for the required MVP screens and routes."""

from pathlib import Path
import unittest

FRONTEND_DIR = Path(__file__).resolve().parents[1]
HTML = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
JAVASCRIPT = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
STYLES = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")


class FrontendContractTests(unittest.TestCase):
    def test_required_views_and_forms_exist(self):
        for identifier in (
            "loginView",
            "registerView",
            "dashboardView",
            "detailsView",
            "bucketView",
            "profileView",
            "adminView",
            "loginForm",
            "registerForm",
            "searchForm",
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
            "/api/bucket-list",
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

    def test_invalid_login_is_not_treated_as_an_expired_session(self):
        self.assertIn(
            "isExpiredSessionError(error.status, error.code)",
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

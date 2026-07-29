"""Static checks for the deployable MySQL schema and safe seed data."""

from pathlib import Path
import re
import unittest

import bcrypt

DB_DIR = Path(__file__).resolve().parents[1]
SCHEMA = (DB_DIR / "DreamEscapes.sql").read_text(encoding="utf-8")
SEED = (DB_DIR / "seed_data.sql").read_text(encoding="utf-8")
SETUP = (DB_DIR / "setup_mysql.sh").read_text(encoding="utf-8")


class DatabaseSchemaContractTests(unittest.TestCase):
    def test_all_required_tables_exist(self):
        for table in (
            "users",
            "bucket_list_destinations",
            "destination_cache",
            "search_history",
            "admin_audit_logs",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS `{table}`", SCHEMA)

    def test_required_integrity_and_lookup_indexes_exist(self):
        for contract in (
            "uq_users_email",
            "uq_bucket_user_place",
            "fk_bucket_user",
            "idx_bucket_user",
            "idx_bucket_place",
            "idx_cache_place",
            "idx_cache_query",
            "idx_cache_country",
            "idx_cache_categories",
            "idx_history_user",
            "idx_history_created",
            "idx_audit_admin",
            "idx_audit_created",
        ):
            self.assertIn(contract, SCHEMA)

    def test_all_checklist_procedures_exist(self):
        for procedure in (
            "RegisterUser",
            "FindUserByEmail",
            "UpdateProfile",
            "UpdateTravelPreferences",
            "GetBucketListByUserId",
            "AddBucketListItem",
            "CheckDuplicateBucketListItem",
            "UpdateBucketListCategoryTravelLabel",
            "DeleteBucketListItem",
            "GetFreshDestinationCache",
            "GetStaleDestinationCache",
            "UpsertDestinationCache",
            "SaveSearchHistory",
            "GetRecentSearchHistory",
            "GetAllUsersForAdmin",
            "UpdateUserRole",
            "EnableOrDisableUserAccount",
            "InsertAdminAuditLog",
            "GetAdminAuditLogs",
        ):
            self.assertRegex(
                SCHEMA,
                rf"CREATE PROCEDURE `{re.escape(procedure)}`",
            )

    def test_seed_passwords_are_valid_bcrypt_hashes(self):
        hashes = re.findall(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", SEED)
        self.assertGreaterEqual(len(hashes), 2)
        for password_hash in hashes:
            self.assertTrue(
                bcrypt.checkpw(
                    b"DreamEscapesDemo123!",
                    password_hash.encode("utf-8"),
                )
            )

    def test_schema_contains_no_root_definer_or_plaintext_password(self):
        self.assertNotIn("DEFINER=", SCHEMA.upper())
        self.assertNotRegex(SCHEMA.lower(), r"password\s+varchar")

    def test_setup_grants_permissions_required_by_schema_assertions(self):
        """Keep the documented app-user test command executable."""
        self.assertIn(
            "GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, "
            "CREATE ROUTINE, ALTER ROUTINE",
            SETUP,
        )
        self.assertIn(r"ON \`${DB_NAME}\`.* TO", SETUP)

    def test_setup_synchronizes_django_migrations_with_existing_schema(self):
        """Prevent runserver's unapplied-migration warning after DB setup."""
        self.assertIn("Django==6.0.6", SETUP)
        self.assertIn("djangorestframework==3.17.1", SETUP)
        self.assertIn(
            "migrate --fake-initial --noinput --skip-checks",
            SETUP,
        )
        self.assertIn("DB_USER=root", SETUP)


if __name__ == "__main__":
    unittest.main()

"""Static guarantees for RabbitMQ-only authentication."""

from pathlib import Path
import unittest


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]
AUTH_SERVICE = (
    BACKEND_DIR / "services" / "auth_service.py"
).read_text(encoding="utf-8")
MQ_CONFIG = (REPO_ROOT / "mq" / "config.py").read_text(encoding="utf-8")
MQ_IMPLEMENTATION = (REPO_ROOT / "mq" / "rabbitmq.py").read_text(
    encoding="utf-8"
)
MQ_SETUP = (REPO_ROOT / "mq" / "setup-test_mq.sh").read_text(encoding="utf-8")


class RabbitMqOnlyAuthenticationContractTests(unittest.TestCase):
    """Prevent local-auth and shared-response paths from returning."""

    def test_registration_and_login_have_no_local_database_bypass(self):
        self.assertNotIn("USE_AUTH_MQ", AUTH_SERVICE)
        self.assertNotIn("_use_auth_mq", AUTH_SERVICE)
        self.assertNotIn("UserAccount.objects.create", AUTH_SERVICE)
        self.assertNotIn("bcrypt.checkpw", AUTH_SERVICE)
        self.assertIn("_request_auth_command(message)", AUTH_SERVICE)

    def test_shared_response_topology_is_absent(self):
        for retired_contract in (
            "AUTH_RESPONSE_QUEUE",
            "AUTH_RESPONSE_ROUTING_KEY",
            "auth.response.app.queue",
            "publish_auth_request",
        ):
            with self.subTest(contract=retired_contract):
                self.assertNotIn(retired_contract, MQ_CONFIG)
                self.assertNotIn(retired_contract, MQ_IMPLEMENTATION)
        self.assertIn("rabbitmqctl delete_queue", MQ_SETUP)

    def test_only_register_and_login_are_private_auth_commands(self):
        self.assertIn('"auth.register.request"', MQ_CONFIG)
        self.assertIn('"auth.login.request"', MQ_CONFIG)
        self.assertNotIn('"auth.logout.event"', MQ_CONFIG)


if __name__ == "__main__":
    unittest.main()

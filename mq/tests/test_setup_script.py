"""Static contracts for non-fatal RabbitMQ setup diagnostics."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MQ_SETUP = (REPO_ROOT / "mq" / "setup-test_mq.sh").read_text(encoding="utf-8")
MQ_LOGGER_SERVICE = (
    REPO_ROOT / "mq" / "systemd" / "dreamescapes-mq-logger.service.template"
).read_text(encoding="utf-8")
DEPENDENCY_SETUP = (REPO_ROOT / "dependencies_install.sh").read_text(
    encoding="utf-8"
)


class RabbitMqSetupScriptTests(unittest.TestCase):
    """Keep optional broker tests visible without stopping installation."""

    def test_optional_smoke_tests_are_non_fatal(self):
        self.assertIn(
            "if ! python -m mq.smoke_test publish; then",
            MQ_SETUP,
        )
        self.assertIn(
            "if ! python -m mq.smoke_test bad; then",
            MQ_SETUP,
        )
        self.assertGreaterEqual(MQ_SETUP.count("warn_yellow"), 3)
        self.assertIn("Setup will continue", MQ_SETUP)

    def test_final_connectivity_check_has_shell_level_fallback(self):
        self.assertIn("if python - <<'PY'", DEPENDENCY_SETUP)
        self.assertIn("RabbitMQ connectivity test could not run", DEPENDENCY_SETUP)
        self.assertIn("return 0", DEPENDENCY_SETUP)

    def test_centralized_logger_is_installed_as_a_supervised_service(self):
        self.assertIn("dreamescapes-mq-logger", MQ_SETUP)
        self.assertIn("systemctl enable --now", MQ_SETUP)
        self.assertIn("final_features.jsonl", MQ_SETUP)
        self.assertIn("-m mq.listener central", MQ_LOGGER_SERVICE)
        self.assertIn("Restart=always", MQ_LOGGER_SERVICE)


if __name__ == "__main__":
    unittest.main()

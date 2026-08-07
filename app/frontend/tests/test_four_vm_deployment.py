"""Static contracts for the four-VM setup and service boundaries."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SETUP = (REPO_ROOT / "app" / "app_setup.sh").read_text(encoding="utf-8")
NGINX_TEMPLATE = (
    REPO_ROOT / "app" / "frontend" / "nginx" / "dreamescapes.conf.template"
).read_text(encoding="utf-8")
API_SETUP = (REPO_ROOT / "api" / "setup_api.sh").read_text(encoding="utf-8")
API_SERVICE = (
    REPO_ROOT / "api" / "systemd" / "dreamescapes-api.service.template"
).read_text(encoding="utf-8")
DB_CONSUMER = (REPO_ROOT / "db" / "auth_consumer.py").read_text(encoding="utf-8")
DB_SERVICE = (
    REPO_ROOT / "db" / "systemd" / "dreamescapes-db-consumer.service.template"
).read_text(encoding="utf-8")
DEPENDENCIES = (REPO_ROOT / "dependencies_install.sh").read_text(encoding="utf-8")


class FourVmDeploymentTests(unittest.TestCase):
    """Keep APP, API, DB, and MQ runtime responsibilities separated."""

    def test_app_role_is_static_nginx_and_same_origin_proxy(self):
        self.assertIn("apt-get install -y curl nginx", APP_SETUP)
        self.assertIn("proxy_pass http://__API_HOST__:__API_PORT__", NGINX_TEMPLATE)
        self.assertIn("location /api/", NGINX_TEMPLATE)
        self.assertNotIn("pip install", APP_SETUP)
        self.assertNotIn("RABBITMQ", APP_SETUP)

    def test_api_role_uses_gunicorn_service(self):
        self.assertIn("requirements.txt", API_SETUP)
        self.assertIn("systemctl enable --now", API_SETUP)
        self.assertIn("gunicorn", API_SERVICE)
        self.assertIn("0.0.0.0", API_SETUP)
        self.assertNotIn("APP_SETUP_SCRIPT", API_SETUP)

    def test_db_consumer_loads_private_env_before_mq_config(self):
        env_load = DB_CONSUMER.index("load_dotenv(Path(__file__).with_name")
        mq_import = DB_CONSUMER.index("from mq.config import")
        self.assertLess(env_load, mq_import)
        self.assertIn("Restart=always", DB_SERVICE)

    def test_main_installer_has_independent_role_selection(self):
        for variable in (
            "RUN_APP_ROLE",
            "RUN_API_ROLE",
            "RUN_DB_ROLE",
            "RUN_MQ_ROLE",
        ):
            self.assertIn(variable, DEPENDENCIES)
        self.assertIn("export API_HOST", DEPENDENCIES)
        self.assertIn("export DB_APP_HOST", DEPENDENCIES)


if __name__ == "__main__":
    unittest.main()

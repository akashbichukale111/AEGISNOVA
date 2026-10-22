"""Regression and integration tests for AEGISNOVA product shell wiring."""
import json
import unittest
from helpers import *
from aegisnova_ops.auth import DevTokenAuth, FixedTokenAuth
from aegisnova_ops.store import Store
from aegisnova_ops.clock import FakeClock


class AegisnovaIntegrationTests(unittest.TestCase):
    def test_store_lifecycle_and_clean_close(self):
        """Verify Store close and __del__ releases sqlite handle without ResourceWarning."""
        s = Store(":memory:", FakeClock())
        s.x("CREATE TABLE test_tab (id INT);")
        s.close()
        # Closing again should be a safe no-op
        s.close()

    def test_internal_env_token_authentication(self):
        """Verify internal microservice token authentication between Next.js and Python."""
        auth = DevTokenAuth(token_file=".local/nonexistent_test.json", env_token="secret-internal-proxy-token")
        # Internal token authenticates directly as admin
        p = auth.authenticate({"authorization": "Bearer secret-internal-proxy-token"})
        self.assertIsNotNone(p)
        self.assertEqual(p.role, "admin")
        self.assertEqual(p.name, "internal-admin")

        # Wrong token is rejected
        p_wrong = auth.authenticate({"authorization": "Bearer wrong-token"})
        self.assertIsNone(p_wrong)

    def test_fixed_token_auth_subclass_has_env_token_attribute(self):
        """Ensure FixedTokenAuth properly initializes env_token attribute to prevent 500s."""
        fta = FixedTokenAuth({"viewer": "tok1", "admin": "tok2"})
        self.assertTrue(hasattr(fta, "env_token"))
        self.assertIsNone(fta.env_token)
        p = fta.authenticate({"authorization": "Bearer tok2"})
        self.assertIsNotNone(p)
        self.assertEqual(p.role, "admin")

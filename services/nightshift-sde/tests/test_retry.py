import random
import socket
import unittest
import urllib.error

from nightshift.errors import PermanentError, TransientError
from nightshift.retry import (classify_exception, classify_http_status, compute_delay, normalize_policy, recovery_hint, validate_policy)


class RetryTests(unittest.TestCase):
    policy = normalize_policy({"base_seconds": 5, "max_seconds": 300})

    def test_backoff_is_exponential_jittered_and_bounded(self):
        rng = random.Random(1)
        for n in range(1, 12):
            ceiling = min(300.0, 5.0 * 2 ** (n - 1))
            for _ in range(200):
                d = compute_delay(n, self.policy, rng=rng)
                self.assertGreaterEqual(d, ceiling / 2 - 1e-9)
                self.assertLessEqual(d, ceiling + 1e-9)
                self.assertLessEqual(d, 300.0)

    def test_jitter_actually_varies(self):
        rng = random.Random(2)
        self.assertGreater(len({round(compute_delay(4, self.policy, rng=rng), 3) for _ in range(50)}), 20)

    def test_retry_after_raises_floor_but_never_exceeds_cap(self):
        self.assertGreaterEqual(compute_delay(1, self.policy, retry_after=100, rng=random.Random(3)), 100)
        self.assertEqual(compute_delay(1, self.policy, retry_after=10_000, rng=random.Random(3)), 300.0)

    def test_policy_validation(self):
        self.assertEqual(validate_policy(self.policy), [])
        self.assertTrue(validate_policy({**self.policy, "max_attempts": 0}))
        self.assertTrue(validate_policy({**self.policy, "max_attempts": 99}))
        self.assertTrue(validate_policy({**self.policy, "base_seconds": 400}))
        self.assertTrue(validate_policy({**self.policy, "base_seconds": True}))

    def test_classification(self):
        self.assertEqual(classify_exception(TransientError("X"))[0], "transient")
        self.assertEqual(classify_exception(PermanentError("Y"))[0], "permanent")
        self.assertEqual(classify_exception(socket.timeout())[0], "transient")
        self.assertEqual(classify_exception(ConnectionResetError())[0], "transient")
        self.assertEqual(classify_exception(ValueError("bad"))[0], "permanent")
        self.assertEqual(classify_exception(RuntimeError("???"))[0], "transient")  # unknown: bounded retry, not silent wedge

    def test_http_status_mapping(self):
        self.assertIsInstance(classify_http_status(429, 7), TransientError)
        self.assertEqual(classify_http_status(429, 7).retry_after, 7)
        self.assertIsInstance(classify_http_status(503), TransientError)
        self.assertIsInstance(classify_http_status(401), PermanentError)
        self.assertEqual(classify_http_status(401).code, "PROVIDER_AUTH_FAILED")
        self.assertIsInstance(classify_http_status(400), PermanentError)
        e = urllib.error.HTTPError("http://x", 502, "bad gateway", {}, None)
        self.assertEqual(classify_exception(e)[:2], ("transient", "PROVIDER_UNAVAILABLE"))

    def test_every_hint_is_actionable(self):
        for code in ("PROVIDER_AUTH_FAILED", "APPROVAL_EXPIRED", "REGRESSION_TESTS_FAILED", "VERIFIER_DISAGREEMENT", "LEASE_EXPIRED"):
            self.assertGreater(len(recovery_hint(code)), 30)


if __name__ == "__main__":
    unittest.main()

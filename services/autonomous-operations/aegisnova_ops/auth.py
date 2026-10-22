"""Authentication/authorization. Dev-token mode is NON-PRODUCTION and clearly labelled.
Production must supply an AuthProvider (see INTEGRATION_CONTRACT.md); until then mutating routes refuse."""
import hmac
import json
import os
import secrets
import stat
import time
from collections import namedtuple

Principal = namedtuple("Principal", "name role")
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


class AuthProvider:
    label = "abstract"
    def authenticate(self, headers):
        raise NotImplementedError


class DevTokenAuth(AuthProvider):
    label = "dev-token (NON-PRODUCTION)"

    def __init__(self, token_file, env_token=None):
        self.token_file = token_file
        self.env_token = env_token
        self.tokens = self._load()

    def _load(self):
        if os.path.exists(self.token_file):
            with open(self.token_file) as f:
                return json.load(f)
        os.makedirs(os.path.dirname(self.token_file) or ".", exist_ok=True)
        toks = {r: secrets.token_urlsafe(32) for r in ("viewer", "operator", "admin")}
        fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            json.dump(toks, f)
        return toks

    def authenticate(self, headers):
        h = headers.get("authorization", "")
        if not h.lower().startswith("bearer "):
            return None
        tok = h[7:].strip()
        if self.env_token and hmac.compare_digest(tok, self.env_token):
            return Principal("internal-admin", "admin")
        for role, t in self.tokens.items():
            if hmac.compare_digest(tok, t):
                return Principal(f"dev-{role}", role)
        return None


class FixedTokenAuth(DevTokenAuth):
    """Test helper: explicit tokens, no file."""
    def __init__(self, tokens):
        self.tokens = tokens
        self.env_token = None


class UnconfiguredExternalAuth(AuthProvider):
    label = "external auth UNCONFIGURED (all requests refused)"
    def authenticate(self, headers):
        return None


class RateLimiter:
    def __init__(self, capacity=60, refill_per_s=20.0, now=time.monotonic):
        self.cap, self.refill, self.now, self.b = capacity, refill_per_s, now, {}

    def allow(self, key):
        t = self.now()
        tokens, last = self.b.get(key, (self.cap, t))
        tokens = min(self.cap, tokens + (t - last) * self.refill)
        if tokens < 1:
            self.b[key] = (tokens, t)
            return False
        self.b[key] = (tokens - 1, t)
        return True

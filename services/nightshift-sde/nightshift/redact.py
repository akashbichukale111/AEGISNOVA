"""Secret redaction applied to logs, events, artifacts and API error payloads."""
from __future__ import annotations

import logging
import re
import threading

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:private-key]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-access-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "[REDACTED:api-key]"),
    (re.compile(r"\btvly-[A-Za-z0-9_-]{16,}"), "[REDACTED:api-key]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)\b(aws_secret_access_key|client_secret|secret|password|passwd|token|api[_-]?key|authorization)"
            r"(\s*[:=]\s*)[\"']?([^\s\"',;]{6,})"
        ),
        r"\1\2[REDACTED]",
    ),
]

_SENSITIVE_KEYS = re.compile(
    r"(?i)^(token|secret|password|passwd|authorization|api[_-]?key|private[_-]?key|webhook[_-]?secret|signature)$"
)


class Redactor:
    def __init__(self):
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str | None) -> None:
        """Register an exact secret value (e.g. a configured token) to scrub wherever it appears."""
        if value and len(value) >= 6:
            with self._lock:
                self._secrets.add(value)

    def text(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            return value
        with self._lock:
            secrets = list(self._secrets)
        for s in secrets:
            if s in value:
                value = value.replace(s, "[REDACTED]")
        for pattern, repl in _PATTERNS:
            value = pattern.sub(repl, value)
        return value

    def obj(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if isinstance(k, str) and _SENSITIVE_KEYS.match(k) and v not in (None, "", False):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = self.obj(v)
            return out
        if isinstance(value, (list, tuple)):
            return [self.obj(v) for v in value]
        return value


REDACTOR = Redactor()


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = REDACTOR.text(record.getMessage())
            record.args = ()
        except Exception:  # never let logging break the app
            pass
        return True


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("nightshift")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger

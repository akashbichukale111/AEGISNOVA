"""Small shared helpers: ids, hashing, redaction, URL validation."""
import hashlib
import ipaddress
import json
import re
import secrets
import socket
from urllib.parse import urlparse


def new_id(prefix):
    return f"{prefix}_{secrets.token_hex(8)}"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(s):
    if isinstance(s, str):
        s = s.encode()
    return hashlib.sha256(s).hexdigest()


_REDACTIONS = [
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "[aws-key-id]"),
    (re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization|signature|callback[_-]?token)\b\s*[=:]\s*\S+"), r"\1=[redacted]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<![\w-])\+?\d{10,15}(?![\w-])"), "[phone]"),
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "[redacted-token]"),
]


def redact(text, limit=300):
    if text is None:
        return None
    s = str(text)
    for pat, rep in _REDACTIONS:
        s = pat.sub(rep, s)
    return s[:limit]


def mask_destination(dest):
    if not dest:
        return None
    if "@" in dest:
        local, _, dom = dest.partition("@")
        return (local[:1] + "***@" + dom)
    return "***" + dest[-4:] if len(dest) > 4 else "***"


def validate_https_url(url, allowed_hosts=None, resolve=False):
    """SSRF guard: https only, no userinfo, no loopback/private/link-local targets."""
    if not isinstance(url, str) or not url:
        raise ValueError("url required")
    p = urlparse(url)
    if p.scheme != "https":
        raise ValueError("only https URLs are allowed")
    if p.username or p.password:
        raise ValueError("credentials in URL are not allowed")
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError("missing host")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("local hostnames are not allowed")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError("host not in allowlist")

    def _check_ip(ip):
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError("private/loopback/link-local destination rejected")

    try:
        _check_ip(ipaddress.ip_address(host))
    except ValueError as e:
        if "rejected" in str(e):
            raise
        if resolve:
            for info in socket.getaddrinfo(host, p.port or 443):
                _check_ip(ipaddress.ip_address(info[4][0]))
    return url

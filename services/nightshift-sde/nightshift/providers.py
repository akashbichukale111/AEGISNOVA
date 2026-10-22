"""Advisory evidence providers + a runner that records every real call and keeps honest health state.

Providers
* ``LocalFileProvider`` — reads a local advisory snapshot file. Mode label: ``local-file``. The snapshot's own
  ``generated_at`` is the evidence timestamp, so evidence age is the age of the data, not of the read.
* ``OSVProvider`` — optional live adapter for the OSV query API (disabled unless NIGHTSHIFT_OSV_ENABLED=1).
  Transport is injectable; the endpoint must be HTTPS and must not resolve to a private address (SSRF guard).

A provider is only reported as ``ok`` after a real successful call. Never ``connected`` by configuration alone.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PermanentError, TransientError
from .retry import classify_exception, classify_http_status
from .store import Store
from .untrusted import sanitize
from .util import Clock, iso, parse_iso, sha256_hex, canonical_json
from .versions import SUPPORTED_ECOSYSTEMS

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass
class ProviderResult:
    provider: str
    mode: str
    advisories: list
    retrieved_at: str
    content_hash: str


def _norm_sev(s) -> str:
    s = str(s or "").upper()
    if s == "MODERATE":
        s = "MEDIUM"
    return s if s in SEVERITIES else "UNKNOWN"


def normalize_advisory(raw: dict, provider: str, ecosystem: str, package: str) -> dict:
    """Validate/normalise an advisory. Free text is sanitised (untrusted); structure is strictly checked."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise PermanentError("PROVIDER_BAD_RESPONSE", "advisory missing id")
    ranges = []
    for r in raw.get("ranges") or []:
        if not isinstance(r, dict):
            raise PermanentError("PROVIDER_BAD_RESPONSE", f"{raw['id']}: malformed range")
        ranges.append({k: str(r[k]) for k in ("introduced", "fixed", "last_affected") if r.get(k) not in (None, "")})
    if not ranges:
        raise PermanentError("PROVIDER_BAD_RESPONSE", f"{raw['id']}: advisory has no affected ranges")
    return {
        "id": sanitize(raw["id"], 80),
        "aliases": [sanitize(a, 80) for a in (raw.get("aliases") or []) if isinstance(a, str)][:10],
        "package": package,
        "ecosystem": ecosystem,
        "summary": sanitize(raw.get("summary", ""), 300),
        "severity": _norm_sev(raw.get("severity")),
        "ranges": ranges,
        "url": sanitize(raw.get("url", ""), 300) or None,
        "published": sanitize(raw.get("published", ""), 40) or None,
        "source": provider,
    }


class LocalFileProvider:
    name = "local-advisories"
    mode = "local-file"

    def __init__(self, path: Path, clock: Clock | None = None, name: str | None = None):
        self.path = Path(path)
        self.clock = clock or Clock()
        if name:
            self.name = name  # instance override, e.g. a second local snapshot used to exercise evidence conflicts

    def configured(self) -> bool:
        return self.path.is_file()

    def _load(self):
        if not self.path.is_file():
            raise PermanentError("PROVIDER_NOT_CONFIGURED", "advisory snapshot file not found")
        raw = self.path.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise PermanentError("PROVIDER_BAD_RESPONSE", "advisory snapshot too large")
        try:
            data = json.loads(raw)
            gen = data["generated_at"]
            parse_iso(gen)
            advisories = data["advisories"]
            if not isinstance(advisories, list):
                raise ValueError("advisories must be a list")
        except (ValueError, KeyError, TypeError) as e:
            raise PermanentError("PROVIDER_BAD_RESPONSE", f"invalid advisory snapshot: {e}")
        return data, gen, sha256_hex(raw)

    def lookup(self, ecosystem: str, package: str) -> ProviderResult:
        data, gen, digest = self._load()
        out = []
        for a in data["advisories"]:
            if isinstance(a, dict) and a.get("ecosystem") == ecosystem and a.get("package") == package:
                out.append(normalize_advisory(a, self.name, ecosystem, package))
        return ProviderResult(self.name, self.mode, out, gen, digest)

    def describe(self) -> dict:
        try:
            data, gen, _ = self._load()
            return {"label": sanitize(data.get("label", ""), 120), "generated_at": gen, "advisory_count": len(data["advisories"])}
        except PermanentError as e:
            return {"error": e.code}


def validate_https_url(url: str, *, allow_private: bool = False) -> urllib.parse.ParseResult:
    """SSRF guard: https only, no credentials in URL, host must not resolve to private/loopback/link-local."""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise PermanentError("UNSAFE_URL", "only credential-free https URLs are allowed")
    if not allow_private:
        try:
            infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise TransientError("PROVIDER_UNAVAILABLE", "could not resolve host")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise PermanentError("UNSAFE_URL", "URL resolves to a non-public address")
    return p


class OSVProvider:
    name = "osv"
    mode = "live"

    def __init__(self, url: str, clock: Clock | None = None, transport=None):
        self.url = url
        self.clock = clock or Clock()
        self._transport = transport or self._http_post

    def configured(self) -> bool:
        return True

    def _http_post(self, url: str, body: bytes):
        validate_https_url(url)  # raises on unsafe URL (SSRF guard)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "nightshift-sde/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise PermanentError("PROVIDER_BAD_RESPONSE", "response too large")
                return resp.status, data
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After") if e.headers else None
            raise classify_http_status(e.code, float(ra) if ra and ra.isdigit() else None)

    def lookup(self, ecosystem: str, package: str) -> ProviderResult:
        body = json.dumps({"package": {"name": package, "ecosystem": ecosystem}}).encode()
        status, data = self._transport(self.url, body)
        if status != 200:
            raise classify_http_status(status)
        try:
            doc = json.loads(data)
        except ValueError:
            raise PermanentError("PROVIDER_BAD_RESPONSE", "response was not JSON")
        advisories = []
        for v in doc.get("vulns", []) or []:
            ranges = []
            for aff in v.get("affected", []) or []:
                pkg = aff.get("package", {})
                if pkg.get("name") != package or pkg.get("ecosystem") != ecosystem:
                    continue
                for rg in aff.get("ranges", []) or []:
                    cur = {}
                    for ev in rg.get("events", []) or []:
                        if "introduced" in ev:
                            cur = {"introduced": ev["introduced"]}
                        elif "fixed" in ev:
                            cur["fixed"] = ev["fixed"]
                            ranges.append(cur)
                            cur = {}
                        elif "last_affected" in ev:
                            cur["last_affected"] = ev["last_affected"]
                            ranges.append(cur)
                            cur = {}
                    if cur:
                        ranges.append(cur)
            if not ranges:
                continue
            sev = (v.get("database_specific") or {}).get("severity")
            advisories.append(normalize_advisory(
                {"id": v.get("id"), "aliases": v.get("aliases"), "summary": v.get("summary", ""), "severity": sev,
                 "ranges": ranges, "url": f"https://osv.dev/vulnerability/{v.get('id')}", "published": v.get("published")},
                self.name, ecosystem, package))
        return ProviderResult(self.name, self.mode, advisories, iso(self.clock.now()), sha256_hex(data))


class ProviderRunner:
    """Calls providers, records each call (latency/error), and maintains honest provider_health rows."""

    def __init__(self, store: Store, providers: list, clock: Clock | None = None):
        self.store = store
        self.providers = providers
        self.clock = clock or store.clock

    # -- health bookkeeping ------------------------------------------------------------
    def _record(self, provider, op: str, ok: bool, latency_ms: int, code: str | None, corr: str | None):
        now = iso(self.clock.now())
        with self.store.db.tx() as c:
            c.execute("INSERT INTO provider_calls(provider, operation, ok, latency_ms, error_code, at, correlation_id) VALUES (?,?,?,?,?,?,?)",
                      (provider.name, op, 1 if ok else 0, latency_ms, code, now, corr))
            row = c.execute("SELECT * FROM provider_health WHERE provider=?", (provider.name,)).fetchone()
            fails = 0 if ok else ((row["consecutive_failures"] if row else 0) + 1)
            status = "ok" if ok else ("down" if fails >= 3 else "degraded")
            c.execute(
                "INSERT INTO provider_health(provider, mode, status, last_check_at, last_success_at, consecutive_failures, last_error_code, detail)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET mode=excluded.mode, status=excluded.status,"
                " last_check_at=excluded.last_check_at, last_success_at=COALESCE(excluded.last_success_at, provider_health.last_success_at),"
                " consecutive_failures=excluded.consecutive_failures, last_error_code=excluded.last_error_code",
                (provider.name, provider.mode, status, now, now if ok else None, fails, code, None),
            )

    def check(self, provider, corr: str | None = None) -> dict:
        """Real connectivity/validity check (used by the Settings 'Check' action)."""
        t0 = time.monotonic()
        try:
            if isinstance(provider, LocalFileProvider):
                provider._load()
            else:
                provider.lookup("PyPI", "nightshift-healthcheck-nonexistent-package")
            self._record(provider, "check", True, int((time.monotonic() - t0) * 1000), None, corr)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 — classified below
            kind, code, _ = classify_exception(e)
            self._record(provider, "check", False, int((time.monotonic() - t0) * 1000), code, corr)
            return {"ok": False, "code": code, "kind": kind}

    def lookup_all(self, ecosystem: str, package: str, corr: str | None = None) -> tuple[list[ProviderResult], list[dict]]:
        """Return (results, limitations). Raises TransientError if any provider failed transiently, and
        PermanentError if every provider failed permanently (or none are configured)."""
        if ecosystem not in SUPPORTED_ECOSYSTEMS:
            raise PermanentError("UNSUPPORTED_ECOSYSTEM", ecosystem)
        results, limitations, transient = [], [], None
        permanent_errors = []
        active = [p for p in self.providers if p.configured()]
        if not active:
            raise PermanentError("NO_ADVISORY_PROVIDER", "no advisory provider is configured; cannot assess dependencies")
        for p in active:
            t0 = time.monotonic()
            try:
                res = p.lookup(ecosystem, package)
                self._record(p, "lookup", True, int((time.monotonic() - t0) * 1000), None, corr)
                results.append(res)
            except Exception as e:  # noqa: BLE001
                kind, code, retry_after = classify_exception(e)
                self._record(p, "lookup", False, int((time.monotonic() - t0) * 1000), code, corr)
                if kind == "transient":
                    transient = transient or TransientError(code, str(e), retry_after=retry_after)
                else:
                    permanent_errors.append((p.name, code))
                    limitations.append({"code": "PROVIDER_FAILED", "provider": p.name, "error": code})
        if transient:
            raise transient
        if not results:
            raise PermanentError(permanent_errors[0][1], f"all advisory providers failed: {permanent_errors}")
        return results, limitations

    def health(self) -> list[dict]:
        rows = self.store.db.read().execute("SELECT * FROM provider_health ORDER BY provider").fetchall()
        return [dict(r) for r in rows]

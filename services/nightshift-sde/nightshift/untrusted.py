"""Untrusted-content handling.

Repository text, advisory prose, issue comments, logs and web pages are DATA. NightShift's pipeline
never feeds them to an instruction-following component; decisions (risk, policy, approval, retries,
transitions) are deterministic code. This module sanitises such text for display/storage and flags
instruction-like content for human visibility.
"""
from __future__ import annotations

import re

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"\s+")

INJECTION_PATTERNS = [
    ("ignore_instructions", re.compile(r"(?i)\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,40}\b(instructions?|rules?|policy|policies)\b")),
    ("role_override", re.compile(r"(?i)\b(you are now|act as|new instructions?:|system prompt|developer message)\b")),
    ("approve_or_merge", re.compile(r"(?i)\b(approve|accept|merge|deploy)\b.{0,30}\b(this|the)\b.{0,20}\b(change|patch|pr|pull request|release)\b")),
    ("policy_tamper", re.compile(r"(?i)\b(set|change|disable|override)\b.{0,30}\b(policy|approval|sandbox|safety|gate)s?\b")),
    ("grant_permission", re.compile(r"(?i)\bgrant\b.{0,30}\b(permission|approval|access|admin)\b")),
    ("exfiltrate", re.compile(r"(?i)\b(exfiltrate|send|post|upload)\b.{0,40}\b(secrets?|tokens?|credentials?|env(ironment)?)\b")),
    ("chat_template_marker", re.compile(r"(<\|im_start\|>|<\|system\|>|\[INST\]|###\s*system)", re.I)),
]


def sanitize(text, max_len: int = 400) -> str:
    """Strip control characters, collapse whitespace, cap length. Result is plain data, never markup."""
    if text is None:
        return ""
    s = _CTRL.sub("", str(text))
    s = _WS.sub(" ", s).strip()
    return s[:max_len] + ("…" if len(s) > max_len else "")


def scan_text(text: str, path: str) -> list[dict]:
    """Return injection-like findings (visibility only; they never alter decisions)."""
    flags = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 2000:
            line = line[:2000]
        for pid, pat in INJECTION_PATTERNS:
            if pat.search(line):
                flags.append({"path": path, "line": i, "pattern": pid, "excerpt": sanitize(line, 120)})
                break
        if len(flags) >= 50:
            break
    return flags

"""Version parsing/comparison for PyPI (PEP 440 subset) and npm (semver) plus OSV-style range matching.

If a version string cannot be parsed, ``VersionParseError`` is raised and callers must NOT claim a match
or a fix — they report a limitation instead.
"""
from __future__ import annotations

import re

PYPI = "PyPI"
NPM = "npm"
SUPPORTED_ECOSYSTEMS = (PYPI, NPM)


class VersionParseError(ValueError):
    pass


_PEP440 = re.compile(
    r"^\s*v?(?:(?P<epoch>\d+)!)?(?P<release>\d+(?:\.\d+)*)"
    r"(?:[-_.]?(?P<pre_l>a|b|c|rc|alpha|beta|pre|preview)[-_.]?(?P<pre_n>\d*))?"
    r"(?P<post>(?:-(?P<post_n1>\d+))|(?:[-_.]?(?:post|rev|r)[-_.]?(?P<post_n2>\d*)))?"
    r"(?P<dev>[-_.]?dev[-_.]?(?P<dev_n>\d*))?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?\s*$",
    re.I,
)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2, "pre": 2, "preview": 2}

_SEMVER = re.compile(
    r"^\s*v?(?P<maj>0|[1-9]\d*)\.(?P<min>0|[1-9]\d*)\.(?P<pat>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\s*$"
)

_INF = float("inf")


def _release_key(parts: list[int]) -> tuple:
    p = list(parts)
    while len(p) > 1 and p[-1] == 0:
        p.pop()
    return tuple(p)


def pep440_key(v: str) -> tuple:
    """Ordering follows PEP 440: dev < pre < final < post (same release)."""
    m = _PEP440.match(v or "")
    if not m:
        raise VersionParseError(f"unparseable PyPI version: {v!r}")
    epoch = int(m.group("epoch") or 0)
    release = _release_key([int(x) for x in m.group("release").split(".")])
    pre_l = m.group("pre_l")
    has_post = m.group("post") is not None
    has_dev = m.group("dev") is not None
    NEG, POS = (-1, 0), (99, 0)
    if pre_l:
        pre = (_PRE_RANK[pre_l.lower()], int(m.group("pre_n") or 0))
    elif not has_post and has_dev:
        pre = NEG
    else:
        pre = POS
    if has_post:
        post = (0, int(m.group("post_n1") or m.group("post_n2") or 0))
    else:
        post = NEG
    dev = (0, int(m.group("dev_n") or 0)) if has_dev else POS
    return (epoch, release, pre, post, dev)


def semver_key(v: str) -> tuple:
    m = _SEMVER.match(v or "")
    if not m:
        raise VersionParseError(f"unparseable semver: {v!r}")
    core = (int(m.group("maj")), int(m.group("min")), int(m.group("pat")))
    pre = m.group("pre")
    if pre is None:
        return core, (1,)
    ids = []
    for ident in pre.split("."):
        ids.append((0, int(ident), "") if ident.isdigit() else (1, 0, ident))
    return core, (0, tuple(ids))


def version_key(ecosystem: str, v: str):
    if ecosystem == PYPI:
        return pep440_key(v)
    if ecosystem == NPM:
        return semver_key(v)
    raise VersionParseError(f"unsupported ecosystem {ecosystem!r}")


def compare(ecosystem: str, a: str, b: str) -> int:
    ka, kb = version_key(ecosystem, a), version_key(ecosystem, b)
    return (ka > kb) - (ka < kb)


def is_valid(ecosystem: str, v: str) -> bool:
    try:
        version_key(ecosystem, v)
        return True
    except VersionParseError:
        return False


def in_ranges(ecosystem: str, version: str, ranges: list[dict]) -> bool:
    """OSV-style events: ``[{introduced, fixed?, last_affected?}]``. ``introduced: "0"`` means from the start.

    Raises VersionParseError when the installed version or a boundary cannot be parsed.
    """
    key = version_key(ecosystem, version)
    for r in ranges:
        intro = r.get("introduced", "0")
        if intro not in (None, "0", ""):
            if key < version_key(ecosystem, intro):
                continue
        fixed, last = r.get("fixed"), r.get("last_affected")
        if fixed:
            if key >= version_key(ecosystem, fixed):
                continue
            return True
        if last:
            if key > version_key(ecosystem, last):
                continue
            return True
        return True  # open-ended range from `introduced`
    return False


def fixed_versions(ranges: list[dict]) -> list[str]:
    return [r["fixed"] for r in ranges if r.get("fixed")]


def jump_kind(ecosystem: str, frm: str, to: str) -> str:
    """'patch' | 'minor' | 'major' | 'other' between two versions (semver-style segments)."""
    def seg(v):
        if ecosystem == PYPI:
            m = _PEP440.match(v or "")
            if not m:
                raise VersionParseError(v)
            nums = [int(x) for x in m.group("release").split(".")]
        else:
            m = _SEMVER.match(v or "")
            if not m:
                raise VersionParseError(v)
            nums = [int(m.group("maj")), int(m.group("min")), int(m.group("pat"))]
        return (nums + [0, 0, 0])[:3]

    a, b = seg(frm), seg(to)
    if b[0] != a[0]:
        return "major" if b[0] > a[0] else "other"
    if b[1] != a[1]:
        return "minor" if b[1] > a[1] else "other"
    if b[2] != a[2]:
        return "patch" if b[2] > a[2] else "other"
    return "other"


def normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

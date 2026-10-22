"""Safe, read-only repository filesystem helpers.

* Repositories are resolved ONLY relative to the configured repository root (never client-supplied paths).
* Symlinks are never followed (symlink attacks); they are counted and skipped.
* Inspection never executes repository code. Git HEAD is read from ``.git`` files directly so a malicious
  repository config (e.g. fsmonitor, hooks) can never run.
* Snapshot identity is a content hash of the working tree (``tree_hash``) — immune to TOCTOU between
  "inspect" and "apply" because the workspace copy is re-hashed and compared.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .errors import PermanentError

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"}
MAX_FILES = 5000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def resolve_repo_path(repo_root: Path, rel_path: str) -> Path:
    """Resolve a registered relative path under repo_root. Rejects absolute paths, traversal and symlink escape."""
    if not rel_path or rel_path.startswith(("/", "\\")) or ".." in Path(rel_path).parts or "\x00" in rel_path:
        raise PermanentError("REPO_UNAVAILABLE", "invalid repository path")
    root = Path(repo_root).resolve()
    p = (root / rel_path).resolve()
    if p == root or root not in p.parents:
        raise PermanentError("REPO_UNAVAILABLE", "repository path escapes the configured repository root")
    if not p.is_dir():
        raise PermanentError("REPO_UNAVAILABLE", "repository directory does not exist")
    return p


def walk_files(root: Path):
    """Yield (relpath, abspath) for regular files; skips SKIP_DIRS; never follows symlinks.

    Returns via generator; use ``list_files`` for counts of skipped symlinks.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            ap = os.path.join(dirpath, fn)
            if os.path.islink(ap) or not os.path.isfile(ap):
                continue
            yield os.path.relpath(ap, root).replace(os.sep, "/"), ap


def list_files(root: Path) -> tuple[list[tuple[str, str]], int]:
    files, symlinks = [], 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                symlinks += 1
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            ap = os.path.join(dirpath, fn)
            if os.path.islink(ap):
                symlinks += 1
                continue
            if not os.path.isfile(ap):
                continue
            size = os.path.getsize(ap)
            if size > MAX_FILE_BYTES:
                raise PermanentError("REPO_TOO_LARGE", f"file exceeds {MAX_FILE_BYTES} bytes: {os.path.relpath(ap, root)}")
            total += size
            files.append((os.path.relpath(ap, root).replace(os.sep, "/"), ap))
            if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise PermanentError("REPO_TOO_LARGE", "repository exceeds snapshot limits")
    return files, symlinks


def tree_hash(root: Path) -> dict:
    files, symlinks = list_files(root)
    h = hashlib.sha256()
    for rel, ap in files:
        with open(ap, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        h.update(rel.encode("utf-8") + b"\x00" + digest.encode() + b"\n")
    return {"tree_hash": h.hexdigest(), "file_count": len(files), "symlinks_skipped": symlinks}


def git_head(root: Path) -> str | None:
    """Read HEAD commit by parsing .git files (no git subprocess, nothing repo-controlled executes)."""
    gd = Path(root) / ".git"
    try:
        if not gd.is_dir():
            return None
        head = (gd / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            if ".." in ref or ref.startswith("/"):
                return None
            rp = gd / ref
            if rp.is_file():
                return rp.read_text().strip()[:64] or None
            packed = gd / "packed-refs"
            if packed.is_file():
                for line in packed.read_text().splitlines():
                    if line and not line.startswith(("#", "^")):
                        sha, _, name = line.partition(" ")
                        if name.strip() == ref:
                            return sha
            return None
        return head[:64] if all(ch in "0123456789abcdef" for ch in head) else None
    except OSError:
        return None


def copy_tree(src: Path, dst: Path) -> int:
    """Copy regular files (same filter as tree_hash) into dst. Returns file count."""
    files, _ = list_files(src)
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    root_dst = dst.resolve()
    n = 0
    for rel, ap in files:
        target = (root_dst / rel).resolve()
        if root_dst not in target.parents:
            raise PermanentError("REPO_UNAVAILABLE", f"unsafe path in repository: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ap, target)
        n += 1
    return n


def safe_join(base: Path, rel: str) -> Path:
    """Join rel under base, rejecting traversal/absolute paths/symlink escapes. Used when applying patches."""
    if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts or "\x00" in rel:
        raise PermanentError("UNSAFE_PATH", f"unsafe path: {rel!r}")
    b = Path(base).resolve()
    p = (b / rel).resolve()
    if b not in p.parents:
        raise PermanentError("UNSAFE_PATH", f"path escapes workspace: {rel!r}")
    return p

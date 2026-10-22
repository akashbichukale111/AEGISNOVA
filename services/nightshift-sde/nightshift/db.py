"""SQLite access: per-thread connections, explicit IMMEDIATE transactions, reviewed SQL migrations."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    # -- connections -------------------------------------------------------------------
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=True)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=15000")
            if self.path != ":memory:":
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
            self._local.depth = 0
        return c

    @contextmanager
    def tx(self):
        """Reentrant write transaction. BEGIN IMMEDIATE serialises writers, which is what makes the
        scheduler tick, lease claims and fenced writes race-free across threads and processes."""
        c = self.conn()
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            c.execute("BEGIN IMMEDIATE")
        self._local.depth = depth + 1
        try:
            yield c
        except BaseException:
            self._local.depth -= 1
            if self._local.depth == 0:
                c.execute("ROLLBACK")
            raise
        else:
            self._local.depth -= 1
            if self._local.depth == 0:
                c.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        return self.conn()

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    # -- migrations --------------------------------------------------------------------
    def _ensure_meta(self, c):
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")

    def applied_versions(self) -> list[str]:
        c = self.conn()
        self._ensure_meta(c)
        return [r["version"] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]

    def migrate_up(self) -> list[str]:
        c = self.conn()
        self._ensure_meta(c)
        done = set(self.applied_versions())
        applied = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name.endswith(".down.sql"):
                continue
            version = f.name.split("_", 1)[0]
            if version in done:
                continue
            sql = f.read_text()
            c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _split_statements(sql):
                    c.execute(stmt)
                c.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (version,),
                )
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            applied.append(version)
        return applied

    def migrate_down(self) -> list[str]:
        """Roll back the most recently applied migration (destructive for its tables)."""
        c = self.conn()
        self._ensure_meta(c)
        versions = self.applied_versions()
        if not versions:
            return []
        last = versions[-1]
        down = next(MIGRATIONS_DIR.glob(f"{last}_*.down.sql"), None)
        if down is None:
            raise RuntimeError(f"no down migration for {last}")
        c.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split_statements(down.read_text()):
                c.execute(stmt)
            c.execute("DELETE FROM schema_migrations WHERE version=?", (last,))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return [last]


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into statements, keeping CREATE TRIGGER ... END; bodies intact."""
    stmts, buf, in_trigger = [], [], False
    for line in sql.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if upper.endswith("END;"):
                stmts.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf and "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts

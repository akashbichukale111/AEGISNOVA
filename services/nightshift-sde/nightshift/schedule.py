"""Schedules: timezone-aware recurrence maths, schedule management, and the restart-safe scheduler tick.

Duplicate-execution protection (three independent layers):
  1. the tick runs inside one ``BEGIN IMMEDIATE`` transaction, so overlapping ticks (threads/processes) serialise;
  2. ``schedule_runs`` has UNIQUE(schedule_id, scheduled_for);
  3. the job idempotency key is ``schedule:<id>:<scheduled_for>``.

A scheduled job is NOT authorised to write code: ``allow_repair`` is a separate, explicitly granted flag that is
re-checked against the repository at fire time.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import Conflict, NotFound, RateLimited, ValidationError
from .retry import normalize_policy, validate_policy
from .store import Store
from .util import UTC, iso, jdumps, jloads, new_id, parse_iso

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_OCCURRENCES_PER_TICK = 1000


# ---------------------------------------------------------------------------------------------- recurrence maths
def get_tz(name: str) -> ZoneInfo:
    try:
        if not isinstance(name, str) or not name or len(name) > 64:
            raise ZoneInfoNotFoundError(name)
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValidationError(f"unknown timezone {name!r} (use an IANA name such as 'Asia/Kolkata' or 'UTC')", code="INVALID_TIMEZONE")


def parse_hhmm(value) -> time:
    try:
        hh, mm = str(value).split(":")
        if len(hh) != 2 or len(mm) != 2:
            raise ValueError
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        raise ValidationError("'at' must be HH:MM in 24-hour time", code="INVALID_RECURRENCE")


def validate_recurrence(rec) -> dict:
    if not isinstance(rec, dict):
        raise ValidationError("recurrence must be an object", code="INVALID_RECURRENCE")
    t = rec.get("type")
    if t == "interval":
        n = rec.get("every_minutes")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 60 * 24 * 31:
            raise ValidationError("every_minutes must be an integer between 1 and 44640", code="INVALID_RECURRENCE")
        return {"type": "interval", "every_minutes": n}
    if t == "daily":
        return {"type": "daily", "at": parse_hhmm(rec.get("at")).strftime("%H:%M")}
    if t == "weekly":
        days = rec.get("days")
        if not isinstance(days, list) or not days or any(d not in DAYS for d in days):
            raise ValidationError(f"days must be a non-empty list drawn from {DAYS}", code="INVALID_RECURRENCE")
        return {"type": "weekly", "days": sorted(set(days), key=DAYS.index), "at": parse_hhmm(rec.get("at")).strftime("%H:%M")}
    raise ValidationError("recurrence.type must be one of interval, daily, weekly", code="INVALID_RECURRENCE")


def local_to_utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Wall-clock → UTC. DST gap (nonexistent time) shifts forward; DST overlap (ambiguous) picks the first occurrence."""
    return datetime.combine(d, t).replace(tzinfo=tz, fold=0).astimezone(UTC)


def next_after(rec: dict, tz: ZoneInfo, anchor: datetime, after: datetime) -> datetime:
    """First scheduled instant strictly greater than ``after`` (UTC)."""
    after = after.astimezone(UTC)
    t = rec["type"]
    if t == "interval":
        step = timedelta(minutes=rec["every_minutes"])
        if after < anchor:
            return anchor
        k = int((after - anchor) / step) + 1
        return anchor + k * step
    at = parse_hhmm(rec["at"])
    local_after = after.astimezone(tz)
    day = local_after.date() - timedelta(days=1)
    wanted = None if t == "daily" else {DAYS.index(d) for d in rec["days"]}
    for _ in range(400):
        day += timedelta(days=1)
        if wanted is not None and day.weekday() not in wanted:
            continue
        cand = local_to_utc(day, at, tz)
        if cand > after:
            return cand
    raise ValidationError("could not compute next run", code="INVALID_RECURRENCE")


def describe(kind: str, rec: dict | None, tz_name: str, run_at: str | None = None) -> str:
    if kind == "one_time":
        if not run_at:
            return "Once"
        local = parse_iso(run_at).astimezone(get_tz(tz_name))
        return f"Once on {local:%a %d %b %Y at %H:%M} ({tz_name})"
    t = rec["type"]
    if t == "interval":
        n = rec["every_minutes"]
        if n % 1440 == 0:
            return f"Every {n // 1440} day(s)" if n // 1440 > 1 else "Every day (interval)"
        if n % 60 == 0:
            return f"Every {n // 60} hour(s)" if n // 60 > 1 else "Every hour"
        return f"Every {n} minute(s)"
    if t == "daily":
        return f"Every day at {rec['at']} ({tz_name})"
    return f"Every {', '.join(d.capitalize() for d in rec['days'])} at {rec['at']} ({tz_name})"


def preview_runs(kind: str, rec: dict | None, tz_name: str, anchor: datetime, now: datetime, run_at: str | None, n: int = 5) -> list[str]:
    if kind == "one_time":
        return [run_at] if run_at and run_at > iso(now) else []
    tz = get_tz(tz_name)
    out, cur = [], now
    for _ in range(n):
        cur = next_after(rec, tz, anchor, cur)
        out.append(iso(cur))
    return out


# ---------------------------------------------------------------------------------------------- management
SCHEDULE_STATUSES = ("active", "paused", "disabled", "completed", "deleted")


def _schedule(row, store: Store | None = None) -> dict:
    d = dict(row)
    d["recurrence"] = jloads(d["recurrence"])
    d["retry_policy"] = jloads(d["retry_policy"], {})
    d["allow_repair"] = bool(d["allow_repair"])
    try:
        d["recurrence_text"] = describe(d["kind"], d["recurrence"], d["timezone"], d["run_at"])
    except ValidationError:
        d["recurrence_text"] = "invalid"
    return d


class ScheduleManager:
    def __init__(self, store: Store, settings):
        self.store, self.settings = store, settings

    # -- reads
    def get(self, schedule_id: str) -> dict:
        r = self.store.db.read().execute("SELECT * FROM schedules WHERE id=? AND status!='deleted'", (schedule_id,)).fetchone()
        if not r:
            raise NotFound("schedule not found", code="SCHEDULE_NOT_FOUND")
        return _schedule(r)

    def list(self, *, repo_id: str | None = None, status: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM schedules WHERE status!='deleted'", []
        if repo_id:
            q += " AND repo_id=?"
            a.append(repo_id)
        if status:
            q += " AND status=?"
            a.append(status)
        rows = self.store.db.read().execute(q + " ORDER BY name", a).fetchall()
        return [_schedule(r) for r in rows]

    def runs(self, schedule_id: str, limit: int = 20) -> list[dict]:
        rows = self.store.db.read().execute(
            "SELECT * FROM schedule_runs WHERE schedule_id=? ORDER BY scheduled_for DESC LIMIT ?", (schedule_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- validation shared by create/update/preview
    def _normalise(self, body: dict, *, existing: dict | None = None) -> dict:
        b = {**(existing or {}), **{k: v for k, v in body.items() if v is not None}} if existing else dict(body)
        allowed = {"name", "purpose", "repo_id", "kind", "timezone", "recurrence", "run_at", "policy_name", "allow_repair",
                   "concurrency_policy", "misfire_policy", "misfire_grace_seconds", "max_duration_seconds", "retry_policy", "status"}
        unknown = set(body) - allowed - {"run_at_local"}
        if unknown:
            raise ValidationError(f"unknown field(s): {sorted(unknown)}", code="UNKNOWN_FIELD")
        name = str(b.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise ValidationError("name must be 1–80 characters", code="INVALID_NAME")
        purpose = str(b.get("purpose") or "")
        if len(purpose) > 500:
            raise ValidationError("purpose must be at most 500 characters")
        tz_name = b.get("timezone") or "UTC"
        tz = get_tz(tz_name)
        kind = b.get("kind")
        if kind not in ("one_time", "recurring"):
            raise ValidationError("kind must be 'one_time' or 'recurring'", code="INVALID_KIND")
        now = self.store.clock.now()
        rec, run_at = None, None
        if kind == "recurring":
            rec = validate_recurrence(b.get("recurrence"))
        else:
            if body.get("run_at_local"):
                try:
                    run_at_dt = datetime.fromisoformat(str(body["run_at_local"]))
                except ValueError:
                    raise ValidationError("run_at_local must be YYYY-MM-DDTHH:MM", code="INVALID_RUN_AT")
                if run_at_dt.tzinfo is not None:
                    raise ValidationError("run_at_local must not include an offset; the timezone field applies", code="INVALID_RUN_AT")
                run_at = iso(local_to_utc(run_at_dt.date(), run_at_dt.time().replace(second=0, microsecond=0), tz))
            elif b.get("run_at"):
                try:
                    parsed = datetime.fromisoformat(str(b["run_at"]).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("naive")
                    run_at = iso(parsed)
                except (ValueError, TypeError):
                    raise ValidationError("run_at must be an ISO-8601 instant with a UTC offset", code="INVALID_RUN_AT")
            else:
                raise ValidationError("one_time schedules need run_at_local or run_at", code="INVALID_RUN_AT")
            if run_at <= iso(now) and not (existing and existing.get("run_at") == run_at):
                raise ValidationError("run_at must be in the future", code="INVALID_RUN_AT")
        repo_id = b.get("repo_id")
        repo = self.store.get_repo(repo_id) if repo_id else None
        if repo is None or repo["archived_at"]:
            raise ValidationError("repo_id must reference an active repository", code="INVALID_REPO")
        policy_name = b.get("policy_name") or "default"
        self.store.get_policy(policy_name)  # raises POLICY_NOT_FOUND
        for k, lo, hi, dflt in (("misfire_grace_seconds", 0, 86400, 300), ("max_duration_seconds", 60, 86400, 3600)):
            v = b.get(k, dflt)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValidationError(f"{k} must be an integer between {lo} and {hi}")
            b[k] = v
        if b.get("concurrency_policy", "forbid") not in ("forbid", "allow"):
            raise ValidationError("concurrency_policy must be 'forbid' or 'allow'")
        if b.get("misfire_policy", "skip") not in ("skip", "run_once"):
            raise ValidationError("misfire_policy must be 'skip' or 'run_once'")
        rp = normalize_policy(b.get("retry_policy"), {
            "max_attempts": self.settings.retry_max_attempts, "base_seconds": self.settings.retry_base_seconds,
            "max_seconds": self.settings.retry_max_seconds, "max_elapsed_seconds": self.settings.retry_max_elapsed_seconds})
        errs = validate_policy(rp)
        if errs:
            raise ValidationError("; ".join(errs), code="INVALID_RETRY_POLICY")
        allow_repair = bool(b.get("allow_repair", False))
        if allow_repair and not repo["allow_repair"]:
            raise ValidationError("repository is not registered as repair-capable; enable it on the repository first", code="REPAIR_NOT_PERMITTED_FOR_REPO")
        return {"name": name, "purpose": purpose, "repo_id": repo_id, "kind": kind, "timezone": tz_name, "recurrence": rec,
                "run_at": run_at, "policy_name": policy_name, "allow_repair": allow_repair,
                "concurrency_policy": b.get("concurrency_policy", "forbid"), "misfire_policy": b.get("misfire_policy", "skip"),
                "misfire_grace_seconds": b["misfire_grace_seconds"], "max_duration_seconds": b["max_duration_seconds"],
                "retry_policy": rp, "_tz": tz, "_now": now}

    def validate(self, body: dict) -> dict:
        """Dry-run for the Schedule Studio preview. Never persists."""
        n = self._normalise(body)
        anchor = n["_now"]
        return {"valid": True, "recurrence_text": describe(n["kind"], n["recurrence"], n["timezone"], n["run_at"]),
                "next_runs": preview_runs(n["kind"], n["recurrence"], n["timezone"], anchor, n["_now"], n["run_at"]),
                "write_capable": n["allow_repair"],
                "warnings": (["This schedule may propose code changes. Every change still needs approval, passing regression tests and independent verification."]
                             if n["allow_repair"] else [])}

    # -- writes
    def create(self, body: dict, actor: str) -> dict:
        n = self._normalise(body)
        now = n.pop("_now")
        tz = n.pop("_tz")
        sid = new_id("sch")
        anchor = now
        nxt = n["run_at"] if n["kind"] == "one_time" else iso(next_after(n["recurrence"], tz, anchor, now))
        with self.store.db.tx() as c:
            if c.execute("SELECT 1 FROM schedules WHERE name=? AND repo_id=? AND status!='deleted'", (n["name"], n["repo_id"])).fetchone():
                raise Conflict("a schedule with this name already exists for the repository", code="DUPLICATE_SCHEDULE")
            c.execute(
                "INSERT INTO schedules(id, name, purpose, repo_id, kind, timezone, recurrence, run_at, anchor_at, status, policy_name,"
                " allow_repair, concurrency_policy, misfire_policy, misfire_grace_seconds, max_duration_seconds, retry_policy,"
                " next_run_at, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, n["name"], n["purpose"], n["repo_id"], n["kind"], n["timezone"], jdumps(n["recurrence"]) if n["recurrence"] else None,
                 n["run_at"], iso(anchor), "active", n["policy_name"], 1 if n["allow_repair"] else 0, n["concurrency_policy"],
                 n["misfire_policy"], n["misfire_grace_seconds"], n["max_duration_seconds"], jdumps(n["retry_policy"]), nxt,
                 actor, iso(now), iso(now)))
            self.store.emit("schedule.created", actor=actor, schedule_id=sid, repo_id=n["repo_id"],
                            data={"name": n["name"], "kind": n["kind"], "allow_repair": n["allow_repair"], "next_run_at": nxt})
        return self.get(sid)

    def update(self, schedule_id: str, body: dict, actor: str) -> dict:
        cur = self.get(schedule_id)
        merged = {k: cur[k] for k in ("name", "purpose", "repo_id", "kind", "timezone", "recurrence", "run_at", "policy_name",
                                      "allow_repair", "concurrency_policy", "misfire_policy", "misfire_grace_seconds",
                                      "max_duration_seconds", "retry_policy")}
        merged.update({k: v for k, v in body.items() if k != "status"})
        n = self._normalise(merged if "run_at_local" not in body else {**merged, "run_at_local": body["run_at_local"]})
        now = n.pop("_now")
        tz = n.pop("_tz")
        nxt = n["run_at"] if n["kind"] == "one_time" else iso(next_after(n["recurrence"], tz, now, now))
        status = cur["status"]
        if cur["status"] == "completed" and n["kind"] == "one_time" and n["run_at"] != cur["run_at"]:
            status = "active"
        with self.store.db.tx() as c:
            c.execute(
                "UPDATE schedules SET name=?, purpose=?, kind=?, timezone=?, recurrence=?, run_at=?, anchor_at=?, policy_name=?,"
                " allow_repair=?, concurrency_policy=?, misfire_policy=?, misfire_grace_seconds=?, max_duration_seconds=?,"
                " retry_policy=?, next_run_at=?, status=?, updated_at=? WHERE id=?",
                (n["name"], n["purpose"], n["kind"], n["timezone"], jdumps(n["recurrence"]) if n["recurrence"] else None, n["run_at"],
                 iso(now), n["policy_name"], 1 if n["allow_repair"] else 0, n["concurrency_policy"], n["misfire_policy"],
                 n["misfire_grace_seconds"], n["max_duration_seconds"], jdumps(n["retry_policy"]), nxt, status, iso(now), schedule_id))
            self.store.emit("schedule.updated", actor=actor, schedule_id=schedule_id, repo_id=n["repo_id"],
                            data={"fields": sorted(body), "next_run_at": nxt})
        return self.get(schedule_id)

    def set_status(self, schedule_id: str, action: str, actor: str) -> dict:
        target = {"pause": "paused", "resume": "active", "enable": "active", "disable": "disabled"}.get(action)
        if not target:
            raise ValidationError("action must be pause, resume, enable or disable", code="INVALID_ACTION")
        cur = self.get(schedule_id)
        if cur["status"] == "completed" and target == "active":
            raise Conflict("a completed one-time schedule cannot be re-enabled; edit run_at to re-arm it", code="SCHEDULE_COMPLETED")
        now = self.store.clock.now()
        sets = {"status": target, "updated_at": iso(now)}
        if target == "active" and cur["status"] != "active":
            if cur["kind"] == "recurring":
                # no catch-up burst after a pause: the next run is computed from "now"
                sets["next_run_at"] = iso(next_after(cur["recurrence"], get_tz(cur["timezone"]), parse_iso(cur["anchor_at"]), now))
            elif cur["run_at"] <= iso(now):
                raise Conflict("run_at is in the past; edit the schedule to set a new time", code="RUN_AT_PAST")
        with self.store.db.tx() as c:
            c.execute(f"UPDATE schedules SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), schedule_id))
            self.store.emit("schedule." + action, actor=actor, schedule_id=schedule_id, repo_id=cur["repo_id"], data={"to": target})
        return self.get(schedule_id)

    def delete(self, schedule_id: str, actor: str) -> None:
        """Soft delete: history (runs, jobs) is preserved; no further runs fire."""
        cur = self.get(schedule_id)
        with self.store.db.tx() as c:
            c.execute("UPDATE schedules SET status='deleted', deleted_at=?, updated_at=?, next_run_at=NULL WHERE id=?",
                      (iso(self.store.clock.now()), iso(self.store.clock.now()), schedule_id))
            self.store.emit("schedule.deleted", actor=actor, schedule_id=schedule_id, repo_id=cur["repo_id"], data={"name": cur["name"]})


# ---------------------------------------------------------------------------------------------- scheduler tick
class Scheduler:
    def __init__(self, store: Store, settings):
        self.store, self.settings = store, settings

    def tick(self) -> list[dict]:
        """Fire every due schedule exactly once per scheduled instant. Safe to call concurrently and after downtime."""
        fired: list[dict] = []
        now = self.store.clock.now()
        with self.store.db.tx() as c:
            due = c.execute("SELECT * FROM schedules WHERE status='active' AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
                            (iso(now),)).fetchall()
            for row in due:
                s = _schedule(row)
                try:
                    fired.append(self._fire_due(c, s, now))
                except Exception:  # one broken schedule must not block the others
                    self.store.incr("scheduler_errors")
                    raise
        return fired

    def _occurrences(self, s: dict, now: datetime) -> list[datetime]:
        first = parse_iso(s["next_run_at"])
        if s["kind"] == "one_time":
            return [first]
        tz, anchor = get_tz(s["timezone"]), parse_iso(s["anchor_at"])
        out, cur = [first], first
        while len(out) < MAX_OCCURRENCES_PER_TICK:
            cur = next_after(s["recurrence"], tz, anchor, cur)
            if cur > now:
                break
            out.append(cur)
        return out

    def _fire_due(self, c, s: dict, now: datetime) -> dict:
        slots = self._occurrences(s, now)
        latest = slots[-1]
        missed_older = len(slots) - 1
        lateness = (now - latest).total_seconds()
        status = "fired"
        if lateness > s["misfire_grace_seconds"]:
            status = "catchup_fired" if s["misfire_policy"] == "run_once" else "missed_skipped"
        scheduled_for = iso(latest)
        repo = self.store.get_repo(s["repo_id"])
        job_id, note = None, None
        if status != "missed_skipped":
            open_jobs = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE schedule_id=? AND state NOT IN (%s)"
                                  % ",".join("?" * 6), (s["id"], "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED", "EXPIRED", "DEAD_LETTER")).fetchone()["n"]
            if s["concurrency_policy"] == "forbid" and open_jobs > 0:
                status, note = "skipped_concurrency", f"{open_jobs} job(s) of this schedule still open"
            else:
                allow = bool(s["allow_repair"] and repo["allow_repair"])
                if s["allow_repair"] and not repo["allow_repair"]:
                    note = "repository no longer repair-capable; ran as investigation-only"
                try:
                    job, created = self.store.create_job(
                        repo_id=s["repo_id"], trigger_type="schedule", idempotency_key=f"schedule:{s['id']}:{scheduled_for}",
                        requested_by=f"schedule:{s['id']}", trigger_event_id=scheduled_for, allow_repair=allow, schedule_id=s["id"],
                        policy_name=s["policy_name"], retry_policy=s["retry_policy"], deadline_seconds=s["max_duration_seconds"],
                        stage_timeout_seconds=self.settings.stage_timeout_seconds, queue_cap=self.settings.queue_cap_per_repo)
                    job_id = job["id"]
                except RateLimited as e:
                    status, note = "error", f"{e.code}: {e.message}"
        try:
            c.execute("INSERT INTO schedule_runs(id, schedule_id, scheduled_for, fired_at, status, job_id, lateness_seconds, missed_count, note)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      (new_id("run"), s["id"], scheduled_for, iso(now), status, job_id, round(lateness, 3), missed_older, note))
        except sqlite3.IntegrityError:
            status = "duplicate_suppressed"
            self.store.incr("duplicate_trigger_suppressed")
        if s["kind"] == "one_time":
            nxt, new_status = None, "completed"
        else:
            nxt, new_status = iso(next_after(s["recurrence"], get_tz(s["timezone"]), parse_iso(s["anchor_at"]), max(latest, now))), "active"
        c.execute("UPDATE schedules SET next_run_at=?, status=?, last_run_at=?, last_status=?, updated_at=? WHERE id=?",
                  (nxt, new_status, iso(now), status, iso(now), s["id"]))
        if missed_older:
            self.store.incr("schedule_runs_missed", missed_older)
        self.store.incr("scheduler_lateness_samples")
        self.store.emit("schedule.fired", actor="system:scheduler", schedule_id=s["id"], repo_id=s["repo_id"], job_id=job_id,
                        data={"scheduled_for": scheduled_for, "status": status, "lateness_seconds": round(lateness, 3),
                              "missed_older_slots": missed_older, "note": note})
        return {"schedule_id": s["id"], "status": status, "job_id": job_id, "scheduled_for": scheduled_for,
                "lateness_seconds": lateness, "missed_older_slots": missed_older}

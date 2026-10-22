"""Demo seeding: copies the synthetic fixture repositories into the managed repository root, writes synthetic advisory
snapshots (timestamped NOW so evidence is fresh) and registers repositories/schedules. NO jobs, findings, metrics or history are
fabricated: everything the console shows afterwards is produced by real executions the operator triggers."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .service import App, Principal
from .util import iso

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

DEMO_REPOS = [
    ("payments-service", "Payments Service (demo)", dict(allow_repair=True, test_command_key="python-unittest")),
    ("legacy-batch", "Legacy Batch (demo)", dict(allow_repair=False, test_command_key="python-unittest")),
    ("conflict-lab", "Conflict Lab (demo)", dict(allow_repair=True, test_command_key="python-unittest")),
    ("node-storefront", "Node Storefront (demo)", dict(allow_repair=False, test_command_key="none")),
    ("malformed-manifests", "Malformed Manifests (demo)", dict(allow_repair=False, test_command_key="none")),
]


def write_advisory_snapshots(app: App) -> None:
    now = iso(app.clock.now())
    for tmpl, dest in (("demo-advisories.template.json", app.settings.advisory_file),
                       ("demo-advisories-secondary.template.json", app.settings.advisory_file_secondary)):
        data = json.loads((FIXTURES / "advisories" / tmpl).read_text())
        data["generated_at"] = now
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(json.dumps(data, indent=2))


def seed_demo(app: App, admin: Principal, with_schedule: bool = True) -> dict:
    write_advisory_snapshots(app)
    created = []
    for slug, name, opts in DEMO_REPOS:
        dst = Path(app.settings.repo_root) / "demo" / slug
        if not dst.exists():
            shutil.copytree(FIXTURES / "demo-repos" / slug, dst)
        if app.store.get_repo_by_slug(f"demo/{slug}"):
            continue
        repo = app.register_repo(admin, {"name": name, "slug": f"demo/{slug}", "rel_path": f"demo/{slug}", "is_demo": True, **opts})
        created.append(repo["slug"])
    schedules = []
    pay = app.store.get_repo_by_slug("demo/payments-service")
    if with_schedule and pay and not app.schedules.list(repo_id=pay["id"]):
        s = app.schedules.create({"name": "Nightly dependency inspection", "purpose": "Read-only inspection (no write-capable repair).",
                                  "repo_id": pay["id"], "kind": "recurring", "timezone": "Asia/Kolkata",
                                  "recurrence": {"type": "daily", "at": "02:00"}, "allow_repair": False}, admin.actor)
        schedules.append(s["id"])
    return {"repositories_registered": created, "schedules_created": schedules,
            "note": "Demo fixtures are synthetic. No jobs or history were fabricated."}

"""CLI: ``python -m nightshift <command>``  (init | seed-demo | serve | worker | tick | token | migrate | verify-audit)."""
from __future__ import annotations

import argparse
import logging
import sys
import threading

from .config import ROLES, Settings
from .redact import configure_logging


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nightshift", description="NightShift SDE — standalone autonomous repository-engineering engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create data dir, run migrations, generate local dev tokens (0600)")
    sub.add_parser("seed-demo", help="copy synthetic demo repositories + advisory snapshots and register them (no history is fabricated)")
    sp = sub.add_parser("serve", help="run API + console + scheduler + watchdog + worker(s) in one process (local mode)")
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--no-scheduler", action="store_true")
    sp.add_argument("--no-worker", action="store_true")
    sub.add_parser("worker", help="run only a worker loop (shares the same SQLite database)")
    sub.add_parser("tick", help="run one scheduler tick and one watchdog tick, then exit")
    tp = sub.add_parser("token", help="print the local dev token for a role (stored in the 0600 tokens file)")
    tp.add_argument("role", choices=ROLES)
    sub.add_parser("migrate", help="apply pending migrations")
    mp = sub.add_parser("migrate-down", help="roll back the latest migration (DESTRUCTIVE for its tables)")
    mp.add_argument("--yes", action="store_true")
    sub.add_parser("verify-audit", help="verify the audit hash chain")
    args = ap.parse_args(argv)

    configure_logging()
    settings = Settings.from_env()
    if args.cmd == "migrate-down":
        from .db import Database
        if not args.yes:
            print("refusing without --yes (this drops tables of the latest migration)")
            return 2
        db = Database(settings.db_path)
        print("rolled back:", db.migrate_down())
        return 0

    from .service import App, Principal
    if args.cmd == "init":
        settings.ensure_dirs()
        created = settings.generate_dev_tokens()
        app = App(settings)
        print(f"data dir: {settings.data_dir}\nmigrations applied: {app.db.applied_versions()}")
        print("dev tokens: " + ("created (0600) at " + str(settings.tokens_file) if created else "already present at " + str(settings.tokens_file)))
        print("show one with: python -m nightshift token admin")
        return 0
    settings.ensure_dirs()
    if settings.generate_dev_tokens():
        print(f"[nightshift] generated local dev tokens at {settings.tokens_file} (0600)", file=sys.stderr)
    app = App(settings)
    if args.cmd == "token":
        import json
        data = json.loads(settings.tokens_file.read_text()) if settings.tokens_file.exists() else {}
        if args.role not in data:
            print("no file token for that role (env tokens are not echoed)", file=sys.stderr)
            return 1
        print(data[args.role]["token"])
        return 0
    if args.cmd == "migrate":
        print("applied:", app.db.applied_versions())
        return 0
    if args.cmd == "seed-demo":
        from .demo import seed_demo
        print(seed_demo(app, Principal("cli-admin", "admin")))
        return 0
    if args.cmd == "verify-audit":
        r = app.store.verify_chain()
        print(r)
        return 0 if r["ok"] else 1
    if args.cmd == "tick":
        print("scheduler:", app.scheduler.tick())
        print("watchdog:", app.watchdog.tick())
        return 0
    from .runtime import Runtime
    if args.cmd == "worker":
        rt = Runtime(app, workers=1, scheduler=False, watchdog=False)
        rt.start()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            rt.stop()
        return 0
    if args.cmd == "serve":
        from .server import create_server
        rt = Runtime(app, workers=0 if args.no_worker else args.workers, scheduler=not args.no_scheduler)
        rt.start()
        srv = create_server(app)
        host, port = srv.server_address[:2]
        logging.getLogger("nightshift").info("NightShift SDE listening on http://%s:%s (mode=%s)", host, port, settings.mode)
        print(f"NightShift SDE console: http://{host}:{port}/   (mode: {settings.mode}; tokens: python -m nightshift token <role>)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nshutting down…")
        finally:
            srv.shutdown()
            rt.stop()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

import argparse, json, sys
from . import server, report, parsers


def main(argv=None):
    ap = argparse.ArgumentParser(prog="causal-impact", description="AEGISNOVA Causal Impact Intelligence (standalone)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765)
    a = sub.add_parser("analyze"); a.add_argument("files", nargs="+"); a.add_argument("--incident", required=True)
    a.add_argument("--format", choices=["json", "markdown"], default="markdown")
    v = sub.add_parser("validate"); v.add_argument("files", nargs="+")
    sub.add_parser("demo")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "serve": return server.serve(args.port)
        if args.cmd == "demo": args.files, args.incident, args.format = None, None, "markdown"
        if args.cmd == "demo":
            server.load_demo(); out = server.handle("POST", "/api/v1/export", {"format": "markdown"})[1]["content"]; print(out); return 0
        rf = lambda f: open(f, encoding="utf-8").read()
        files = [{"name": f, "content": rf(f)} for f in args.files]
        res = server.load(files, rf(args.incident) if args.cmd == "analyze" else None)
        if args.cmd == "validate": print(json.dumps(res, indent=2)); return 0
        st, p = server.handle("POST", "/api/v1/export", {"format": args.format})
        print(p["content"] if st == 200 else json.dumps(p)); return 0 if st == 200 else 1
    except (parsers.InputError, OSError) as e:
        print(f"error: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())

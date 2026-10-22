# AEGISNOVA - Workstream 03: Causal Impact Intelligence (standalone)

Evidence-backed dependency graph, root-cause hypotheses, downstream impact, blast radius and counterfactuals.
**Standalone: not merged into the main AEGISNOVA repository, UI or navigation.**
Pure Python 3.11+ standard library: no installs, no cloud credentials, no network calls.

## Quick start
```bash
python3 -m unittest discover -s tests -v        # run tests (offline)
python3 -m causal_impact serve --port 8765      # UI + API at http://127.0.0.1:8765 (click "Load demo fixture")
python3 -m causal_impact demo                   # print a demo markdown report
python3 -m causal_impact validate fixtures/npm/package.json fixtures/python/requirements.txt
python3 -m causal_impact analyze fixtures/demo_service_map.json --incident fixtures/demo_incident.json --format json
```
## Supported input
`package.json`, `package-lock.json` (v2/v3 `packages` map), `requirements.txt`, `pyproject.toml` ([project] table),
generic service-map `*.json` (see GRAPH_SCHEMA.md), incident JSON (see API_AND_SCHEMAS.md).
**Unsupported (rejected with `UNSUPPORTED_FORMAT`):** YAML, CSV, yarn.lock, pnpm-lock, poetry.lock, Pipfile.lock, Maven/Gradle, Go, Cargo, etc.
## Demo data
`fixtures/demo_*` are labelled DEMO and illustrative. Nodes loaded from them carry `attrs.demo_fixture=true`.
## Troubleshooting
Port busy: `--port 8800`. `NO_GRAPH`: import first. `MALFORMED_INPUT`: see the message for file/location. Python < 3.11 lacks `tomllib`.
## Cleanup
Delete the folder; state is in-memory only (no persistence beyond exported reports).

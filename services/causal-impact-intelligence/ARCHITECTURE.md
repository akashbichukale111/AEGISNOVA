# Architecture
- `graph.py` - typed graph, provenance, validation (missing/duplicate/contradictory/cycles/disconnected/unknown versions), bounded BFS, hashing. Domain only.
- `parsers.py` - format detection + parsers + incident parsing, size limit (2 MB/file), stable errors (`InputError.code`).
- `analysis.py` - root-cause rules, impact, blast radius, counterfactuals (operate on a graph COPY). Deterministic; no LLM.
- `report.py` - JSON/Markdown export. `server.py` - stdlib HTTP, binds 127.0.0.1, pure `handle()` router. `cli.py` - CLI. `static/index.html` - UI (all dynamic text escaped via `esc()`).
Persistence: in-memory session only. Optional LLM provider: not implemented; never a source of causal conclusions.

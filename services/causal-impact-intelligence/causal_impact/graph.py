"""Typed, provenance-carrying dependency graph with deterministic traversal."""
import copy, hashlib, json
from collections import deque

NODE_TYPES = {"service", "application", "package", "component", "infrastructure", "datastore", "unknown"}
EDGE_TYPES = {"DEPENDS_ON", "IMPORTS", "CALLS", "DEPLOYED_IN", "RUNS_ON", "PRODUCES",
              "CONSUMES", "AFFECTS", "OBSERVED_BEFORE"}
# Edge "source X target": for these, X depends on target -> impact flows target -> source.
DEPENDENCY_LIKE = {"DEPENDS_ON", "IMPORTS", "CALLS", "DEPLOYED_IN", "RUNS_ON", "CONSUMES"}
# For these, impact flows source -> target.
FORWARD = {"PRODUCES", "AFFECTS"}
# OBSERVED_BEFORE is temporal only and never carries impact.
CLASSES = {"observed", "user_supplied", "inferred"}
MAX_NODES = 20000
MAX_EDGES = 100000


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha(obj, n=16):
    return hashlib.sha256(canon(obj).encode()).hexdigest()[:n]


def edge_id(src, etype, dst):
    return "e:" + sha([src, etype, dst], 12)


class Graph:
    def __init__(self):
        self.nodes, self.edges, self.issues = {}, {}, []

    def issue(self, level, code, msg, **kw):
        self.issues.append({"level": level, "code": code, "message": msg, **kw})

    def add_node(self, node):
        nid = node["node_id"]
        if node.get("node_type") not in NODE_TYPES:
            node["node_type"] = "unknown"
        if nid in self.nodes:
            old = self.nodes[nid]
            diff = [k for k in ("name", "version", "node_type") if old.get(k) != node.get(k)]
            if diff:
                self.issue("warning", "CONFLICTING_NODE", f"{nid} redeclared with different {diff}; first kept", node_id=nid)
            else:
                self.issue("info", "DUPLICATE_NODE", f"{nid} declared more than once; merged", node_id=nid)
            for k, v in node.get("attrs", {}).items():
                old.setdefault("attrs", {}).setdefault(k, v)
            old.setdefault("provenance_all", []).append(node["provenance"])
            return False
        if len(self.nodes) >= MAX_NODES:
            raise ValueError("MAX_NODES exceeded")
        node.setdefault("attrs", {}); node["provenance_all"] = [node["provenance"]]
        self.nodes[nid] = node
        return True

    def add_edge(self, src, etype, dst, provenance, cls="observed", rationale="", attrs=None):
        if etype not in EDGE_TYPES:
            self.issue("error", "UNSUPPORTED_EDGE_TYPE", f"unsupported edge type {etype!r}", source=src, target=dst); return None
        if cls not in CLASSES:
            self.issue("error", "BAD_CLASS", f"relationship class {cls!r} invalid", source=src, target=dst); return None
        for x in (src, dst):
            if x not in self.nodes:
                self.issue("error", "MISSING_NODE", f"edge references unknown node {x!r}; edge rejected", node_id=x); return None
        eid = edge_id(src, etype, dst)
        if eid in self.edges:
            old = self.edges[eid]
            if old["class"] != cls:
                self.issue("warning", "CONTRADICTORY_EDGE", f"{eid} declared as both {old['class']} and {cls}; stronger kept", edge_id=eid)
                rank = {"observed": 0, "user_supplied": 1, "inferred": 2}
                if rank[cls] < rank[old["class"]]:
                    old["class"] = cls
            else:
                self.issue("info", "DUPLICATE_EDGE", f"{eid} declared more than once; merged", edge_id=eid)
            old["provenance_all"].append(provenance)
            return eid
        if len(self.edges) >= MAX_EDGES:
            raise ValueError("MAX_EDGES exceeded")
        self.edges[eid] = {"edge_id": eid, "source_node_id": src, "target_node_id": dst, "edge_type": etype,
                           "direction": ("impact flows source->target" if etype in FORWARD else
                                         "temporal only" if etype == "OBSERVED_BEFORE" else
                                         "source depends on target; impact flows target->source"),
                           "class": cls, "rationale": rationale, "provenance": provenance,
                           "provenance_all": [provenance], "attrs": attrs or {}}
        return eid

    # ---- hashing / copying ----
    def hash(self):
        return sha({"n": {k: [v["node_type"], v["name"], v.get("version")] for k, v in sorted(self.nodes.items())},
                    "e": {k: [v["class"], v["attrs"].get("dep_kind")] for k, v in sorted(self.edges.items())}}, 16)

    def copy(self):
        g = Graph(); g.nodes = copy.deepcopy(self.nodes); g.edges = copy.deepcopy(self.edges)
        g.issues = copy.deepcopy(self.issues); return g

    # ---- adjacency ----
    def impact_adj(self, edge_types=None, exclude_dev=False):
        """node -> sorted [(neighbour, edge)] along which impact propagates."""
        adj = {n: [] for n in self.nodes}
        for e in self.edges.values():
            t = e["edge_type"]
            if t == "OBSERVED_BEFORE" or (edge_types and t not in edge_types):
                continue
            if exclude_dev and e["attrs"].get("dep_kind") in ("dev", "optional"):
                continue
            a, b = e["source_node_id"], e["target_node_id"]
            frm, to = (a, b) if t in FORWARD else (b, a)
            adj[frm].append((to, e))
        for v in adj.values():
            v.sort(key=lambda x: (x[0], x[1]["edge_id"]))
        return adj

    def reverse(self, adj):
        r = {n: [] for n in adj}
        for f, lst in adj.items():
            for t, e in lst:
                r[t].append((f, e))
        for v in r.values():
            v.sort(key=lambda x: (x[0], x[1]["edge_id"]))
        return r

    @staticmethod
    def bfs(adj, start, max_depth=6, max_nodes=500):
        """Bounded BFS. Returns (info, limits). info[n]={depth,path(edges),n_paths} (shortest paths only)."""
        info = {start: {"depth": 0, "path": [], "n_paths": 1}}
        q, limits = deque([start]), {"depth_reached": False, "node_cap_reached": False}
        while q:
            cur = q.popleft(); d = info[cur]["depth"]
            for nb, e in adj.get(cur, []):
                if nb in info:
                    if info[nb]["depth"] == d + 1:
                        info[nb]["n_paths"] += info[cur]["n_paths"]  # duplicate paths collapse to one node
                    continue
                if d + 1 > max_depth:
                    limits["depth_reached"] = True; continue
                if len(info) >= max_nodes:
                    limits["node_cap_reached"] = True; continue
                info[nb] = {"depth": d + 1, "path": info[cur]["path"] + [e], "n_paths": info[cur]["n_paths"]}
                q.append(nb)
        return info, limits

    def upstream(self, nid, max_depth=6, max_nodes=500, edge_types=None):
        """What nid depends on (follow dependency-like edges source->target)."""
        adj = {n: [] for n in self.nodes}
        for e in self.edges.values():
            if e["edge_type"] in DEPENDENCY_LIKE and (not edge_types or e["edge_type"] in edge_types):
                adj[e["source_node_id"]].append((e["target_node_id"], e))
        for v in adj.values(): v.sort(key=lambda x: (x[0], x[1]["edge_id"]))
        return self.bfs(adj, nid, max_depth, max_nodes)

    def downstream(self, nid, max_depth=6, max_nodes=500, edge_types=None, exclude_dev=False):
        return self.bfs(self.impact_adj(edge_types, exclude_dev), nid, max_depth, max_nodes)

    def subgraph(self, nid, max_depth=2, max_nodes=100):
        up, _ = self.upstream(nid, max_depth, max_nodes)
        dn, _ = self.downstream(nid, max_depth, max_nodes)
        ids = set(up) | set(dn)
        return {"nodes": [self.nodes[i] for i in sorted(ids)],
                "edges": [e for e in self.edges.values() if e["source_node_id"] in ids and e["target_node_id"] in ids]}

    # ---- validation ----
    def validate(self):
        out = list(self.issues)
        for n in sorted(self.nodes.values(), key=lambda n: n["node_id"]):
            if n["node_type"] == "package" and not n.get("version"):
                out.append({"level": "warning", "code": "UNKNOWN_VERSION", "node_id": n["node_id"],
                            "message": f"{n['name']} has no exact version (spec: {n['attrs'].get('version_spec', 'none')})"})
        adj = {n: [] for n in self.nodes}
        for e in self.edges.values():
            if e["edge_type"] in DEPENDENCY_LIKE | FORWARD:
                adj[e["source_node_id"]].append(e["target_node_id"])
        for scc in _sccs(adj):
            if len(scc) > 1 or scc[0] in adj[scc[0]]:
                out.append({"level": "info", "code": "CYCLE", "nodes": sorted(scc),
                            "message": "Cycle present. Cycles are legal (e.g. mutual calls); traversal uses visited-sets so it terminates."})
        comps = self.components()
        if len(comps) > 1:
            out.append({"level": "info", "code": "DISCONNECTED", "count": len(comps),
                        "message": f"{len(comps)} disconnected components; impact cannot cross them (possible missing edges)."})
        return out

    def components(self):
        und = {n: set() for n in self.nodes}
        for e in self.edges.values():
            und[e["source_node_id"]].add(e["target_node_id"]); und[e["target_node_id"]].add(e["source_node_id"])
        seen, comps = set(), []
        for n in sorted(und):
            if n in seen: continue
            stack, comp = [n], []
            seen.add(n)
            while stack:
                x = stack.pop(); comp.append(x)
                for y in und[x]:
                    if y not in seen: seen.add(y); stack.append(y)
            comps.append(sorted(comp))
        return comps

    def coverage(self):
        n_e = len(self.edges) or 1
        cls = {c: sum(1 for e in self.edges.values() if e["class"] == c) for c in CLASSES}
        pk = [n for n in self.nodes.values() if n["node_type"] == "package"]
        return {"nodes": len(self.nodes), "edges": len(self.edges), "edge_classes": cls,
                "observed_or_supplied_ratio": round((cls["observed"] + cls["user_supplied"]) / n_e, 2) if self.edges else 0.0,
                "packages_with_unknown_version": sum(1 for n in pk if not n.get("version")),
                "nodes_with_unknown_criticality": sum(1 for n in self.nodes.values() if not n["attrs"].get("criticality")),
                "components": len(self.components())}

    def to_dict(self):
        return {"nodes": [self.nodes[k] for k in sorted(self.nodes)], "edges": [self.edges[k] for k in sorted(self.edges)],
                "graph_hash": self.hash(), "coverage": self.coverage()}


def _sccs(adj):
    idx, low, on, st, res, c = {}, {}, set(), [], [], [0]
    for root in sorted(adj):
        if root in idx: continue
        work = [(root, iter(sorted(adj[root])))]
        idx[root] = low[root] = c[0]; c[0] += 1; st.append(root); on.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in idx:
                    idx[w] = low[w] = c[0]; c[0] += 1; st.append(w); on.add(w)
                    work.append((w, iter(sorted(adj[w])))); adv = True; break
                elif w in on:
                    low[v] = min(low[v], idx[w])
            if adv: continue
            work.pop()
            if work: low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = st.pop(); on.discard(w); comp.append(w)
                    if w == v: break
                res.append(comp)
    return res

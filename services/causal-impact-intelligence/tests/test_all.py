import json, os, sys, threading, unittest, urllib.request, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from causal_impact import parsers, analysis as A, report, server
from causal_impact.graph import Graph
from causal_impact.parsers import InputError

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures")
def rd(p):
    with open(os.path.join(FIX, p), encoding="utf-8") as f: return f.read()


def demo():
    g, _ = parsers.build([{"name": "demo_service_map.json", "content": rd("demo_service_map.json")}])
    return g, parsers.parse_incident(rd("demo_incident.json"))


def smap(nodes, edges):
    return json.dumps({"schema_version": "1", "nodes": nodes, "edges": edges})


def N(i, t="service", **kw): return {"id": i, "type": t, **kw}
def E(s, t, ty="CALLS", **kw): return {"source": s, "target": t, "type": ty, **kw}


class Parsing(unittest.TestCase):
    def test_package_json(self):
        g, _ = parsers.build([{"name": "package.json", "content": rd("npm/package.json")}])
        self.assertIn("pkg:npm/express@4.18.2", g.nodes); self.assertIn("pkg:npm/lodash", g.nodes)
        self.assertIsNone(g.nodes["pkg:npm/lodash"]["version"])           # range => unknown exact version
        self.assertTrue(any(i["code"] == "UNKNOWN_VERSION" for i in g.validate()))
        dev = [e for e in g.edges.values() if e["attrs"]["dep_kind"] == "dev"]; self.assertEqual(len(dev), 1)

    def test_lockfile_nested_resolution(self):
        lock = {"packages": {"": {"name": "app", "version": "1.0.0", "dependencies": {"a": "1"}},
                             "node_modules/a": {"version": "1.0.0", "dependencies": {"b": "1"}},
                             "node_modules/b": {"version": "1.0.0"}, "node_modules/a/node_modules/b": {"version": "2.0.0"},
                             "node_modules/d": {"version": "1.0.0", "dev": True, "dependencies": {"b": "1"}}}}
        g, _ = parsers.build([{"name": "package-lock.json", "content": json.dumps(lock)}])
        self.assertIn(("pkg:npm/a@1.0.0", "pkg:npm/b@2.0.0"), [(e["source_node_id"], e["target_node_id"]) for e in g.edges.values()])
        self.assertTrue(any(e["attrs"]["dep_kind"] == "dev" for e in g.edges.values()))

    def test_requirements_and_pyproject(self):
        g, _ = parsers.build([{"name": "requirements.txt", "content": rd("python/requirements.txt")}])
        self.assertEqual(g.nodes["pkg:pypi/flask@3.0.0"]["version"], "3.0.0"); self.assertIn("pkg:pypi/requests", g.nodes)
        self.assertTrue(any(i["code"] == "SKIPPED_DIRECTIVE" for i in g.issues))
        py = '[project]\nname="x"\nversion="1"\ndependencies=["django==4.2","celery>=5"]\n[project.optional-dependencies]\ndev=["pytest"]'
        g, _ = parsers.build([{"name": "pyproject.toml", "content": py}])
        self.assertIn("pkg:pypi/django@4.2", g.nodes); self.assertEqual(sum(e["attrs"]["dep_kind"] == "optional" for e in g.edges.values()), 1)

    def test_malformed_unsupported_and_limits(self):
        for name, content, code in [("package.json", "{bad", "MALFORMED_INPUT"), ("pyproject.toml", "[[", "MALFORMED_INPUT"),
                                    ("x.yaml", "a: 1", "UNSUPPORTED_FORMAT"), ("m.json", '{"nodes": 1}', "MALFORMED_INPUT"),
                                    ("package.json", "x" * 2_000_001, "INPUT_TOO_LARGE")]:
            with self.assertRaises(InputError) as c: parsers.build([{"name": name, "content": content}])
            self.assertEqual(c.exception.code, code)
        with self.assertRaises(InputError): parsers.build([])
        with self.assertRaises(InputError): parsers.parse_incident({"timestamp": "nope", "affected_component": "a"})

    def test_stable_ids_and_provenance(self):
        g1, _ = demo(); g2, _ = demo()
        self.assertEqual(sorted(g1.edges), sorted(g2.edges)); self.assertEqual(g1.hash(), g2.hash())
        e = next(iter(g1.edges.values())); self.assertTrue(e["provenance"]["location"].startswith("edges["))
        self.assertEqual(len(e["provenance"]["input_sha256"]), 16)
        self.assertTrue(g1.nodes["svc:auth"]["attrs"]["demo_fixture"])


class GraphValidation(unittest.TestCase):
    def build(self, nodes, edges):
        return parsers.build([{"name": "m.json", "content": smap(nodes, edges)}])[0]

    def test_missing_duplicate_contradictory_unsupported(self):
        g = self.build([N("a"), N("b"), N("a")], [E("a", "b"), E("a", "b"), E("a", "zz"), E("a", "b", "FOO"), E("a", "b", class_="x") if False else E("a", "b", **{"class": "inferred"})])
        codes = [i["code"] for i in g.validate()]
        for c in ("DUPLICATE_NODE", "DUPLICATE_EDGE", "MISSING_NODE", "UNSUPPORTED_EDGE_TYPE", "CONTRADICTORY_EDGE"): self.assertIn(c, codes)
        self.assertEqual(len(g.edges), 1)

    def test_cycle_not_error_and_terminates(self):
        g = self.build([N("a"), N("b"), N("c")], [E("a", "b"), E("b", "c"), E("c", "a")])
        v = g.validate(); self.assertTrue(any(i["code"] == "CYCLE" for i in v)); self.assertFalse(any(i["level"] == "error" for i in v))
        info, _ = g.downstream("a"); self.assertEqual(set(info), {"a", "b", "c"})

    def test_disconnected(self):
        g = self.build([N("a"), N("b"), N("c")], [E("a", "b")])
        self.assertTrue(any(i["code"] == "DISCONNECTED" for i in g.validate())); self.assertEqual(g.coverage()["components"], 2)

    def test_traversal_direction_and_caps(self):
        g = self.build([N(x) for x in "abcde"], [E("a", "b"), E("b", "c"), E("c", "d"), E("d", "e")])
        up, _ = g.upstream("a"); self.assertEqual(set(up), set("abcde"))      # a depends on everything
        dn, _ = g.downstream("e"); self.assertEqual(dn["a"]["depth"], 4)       # e failure reaches a
        dn, lim = g.downstream("e", max_depth=2); self.assertEqual(set(dn), {"e", "d", "c"}); self.assertTrue(lim["depth_reached"])
        dn, lim = g.downstream("e", max_nodes=3); self.assertEqual(len(dn), 3); self.assertTrue(lim["node_cap_reached"])
        self.assertEqual(len(g.subgraph("c", 1)["nodes"]), 3)

    def test_observed_before_carries_no_impact_and_forward_edges(self):
        g = self.build([N("a"), N("b"), N("c")], [E("a", "b", "OBSERVED_BEFORE"), E("a", "c", "PRODUCES")])
        dn, _ = g.downstream("a"); self.assertEqual(set(dn), {"a", "c"})


class Impact(unittest.TestCase):
    def test_direct_vs_transitive_and_dedup(self):
        g, _ = demo()
        imp = A.impact(g, "svc:auth")                    # auth <- checkout, frontend (direct) ; frontend also via checkout
        self.assertEqual(sorted(imp["direct"]), ["svc:checkout-api", "svc:web-frontend"])
        self.assertEqual(imp["transitive"], ["svc:notifier"])
        ids = [a["node_id"] for a in imp["affected"]]; self.assertEqual(len(ids), len(set(ids)))
        fe = next(a for a in imp["affected"] if a["node_id"] == "svc:web-frontend")
        self.assertEqual(fe["shortest_path_count"], 1); self.assertEqual(fe["relation"], "direct")

    def test_duplicate_paths_counted_once(self):
        g = parsers.build([{"name": "m.json", "content": smap([N(x) for x in "abcd"], [E("b", "a"), E("c", "a"), E("d", "b"), E("d", "c")])}])[0]
        imp = A.impact(g, "a"); d = next(x for x in imp["affected"] if x["node_id"] == "d")
        self.assertEqual(d["shortest_path_count"], 2); self.assertEqual(len(imp["affected"]), 3)
        self.assertEqual(A.blast_radius(g, imp)["dimensions"]["shortest_path_total"], 4)

    def test_filters_and_unknown_fields(self):
        g, _ = demo()
        self.assertEqual([a["node_id"] for a in A.impact(g, "svc:auth", environment="staging")["affected"]], ["svc:notifier"])
        self.assertEqual([a["node_id"] for a in A.impact(g, "svc:auth", node_types=["datastore"])["affected"]], [])
        n = next(a for a in A.impact(g, "svc:auth")["affected"] if a["node_id"] == "svc:notifier")
        self.assertEqual((n["criticality"], n["owner"]), ("unknown", "unknown"))
        self.assertEqual(A.impact(g, "nope")["status"], "NOT_EVALUABLE")

    def test_exclude_dev(self):
        g, _ = parsers.build([{"name": "package.json", "content": rd("npm/package.json")}])
        self.assertEqual(len(A.impact(g, "pkg:npm/express@4.18.2")["affected"]), 1)
        self.assertEqual(len(A.impact(g, "pkg:npm/jest@29.0.0", exclude_dev=True)["affected"]), 0)


class Blast(unittest.TestCase):
    def test_unknown_criticality_caps_at_moderate(self):
        nodes = [N("root")] + [N(f"s{i}") for i in range(8)]
        g = parsers.build([{"name": "m.json", "content": smap(nodes, [E(f"s{i}", "root") for i in range(8)])}])[0]
        b = A.blast_radius(g, A.impact(g, "root")); self.assertEqual(b["level"], "MODERATE")
        self.assertIsNone(b["dimensions"]["criticality_weighted_score"]); self.assertEqual(b["dimensions"]["criticality_unknown_count"], 8)
        self.assertTrue(any("capped" in r for r in b["rationale"]))

    def test_critical_production_and_weights(self):
        g, inc = demo(); b = A.blast_radius(g, A.impact(g, "svc:auth"))
        self.assertEqual(b["level"], "CRITICAL"); self.assertEqual(b["dimensions"]["criticality_weighted_score"], 4 + 3)
        self.assertEqual(b["dimensions"]["direct_affected"], 2); self.assertEqual(b["dimensions"]["transitive_affected"], 1)
        self.assertEqual(b["dimensions"]["inferred_edges_on_paths"], 1)

    def test_small_noncritical_low_and_unknown_target_and_caps_warning(self):
        g, _ = demo(); self.assertEqual(A.blast_radius(g, A.impact(g, "svc:notifier"))["level"], "LOW")
        self.assertEqual(A.blast_radius(g, A.impact(g, "ghost"))["level"], "UNKNOWN")
        b = A.blast_radius(g, A.impact(g, "svc:auth", max_depth=1)); self.assertTrue(any("limit" in r for r in b["rationale"]))


class RootCause(unittest.TestCase):
    def test_ranking_status_alternatives(self):
        g, inc = demo(); rc = A.root_cause(g, inc); top = rc["candidates"][0]
        self.assertEqual(top["component_id"], "lib:payments-sdk"); self.assertEqual(top["status"], "SUPPORTED_HYPOTHESIS")
        self.assertTrue(top["alternatives"]); self.assertTrue(top["next_diagnostic_check"]); self.assertEqual(top["path_to_symptom"][0]["target"], "lib:payments-sdk"); self.assertEqual(top["path_to_symptom"][-1]["source"], "svc:web-frontend")
        self.assertIn("not proof", rc["caveat"]); self.assertEqual(top["evidence_ids"], ["DEMO-ADV-1", "ev-1"])

    def test_temporal_contradiction(self):
        g, inc = demo(); st = {c["component_id"]: c for c in A.root_cause(g, inc)["candidates"]}
        self.assertEqual(st["svc:auth"]["status"], "CONTRADICTED"); self.assertTrue(st["svc:auth"]["contradicting"])

    def test_no_evidence_is_needs_more_evidence_not_confident(self):
        g, inc = demo(); inc["events"], inc["advisories"] = [], []
        rc = A.root_cause(g, inc); self.assertEqual(rc["overall_status"], "NEEDS_MORE_EVIDENCE")
        self.assertTrue(all(c["status"] == "NEEDS_MORE_EVIDENCE" and c["confidence_band"] == "LOW" for c in rc["candidates"]))

    def test_unknown_component_inconclusive_and_bad_timestamp_noted(self):
        g, inc = demo(); inc2 = dict(inc, affected_component="ghost")
        self.assertEqual(A.root_cause(g, inc2)["overall_status"], "INCONCLUSIVE")
        inc["events"].append({"event_id": "bad", "component": "svc:auth", "type": "change", "timestamp": "garbage"})
        c = next(c for c in A.root_cause(g, inc)["candidates"] if c["component_id"] == "svc:auth"); self.assertTrue(any("bad" in m for m in c["missing_evidence"]))

    def test_old_change_outside_window_scores_lower(self):
        g, inc = demo(); inc["events"][0]["timestamp"] = "2026-03-01T00:00:00Z"
        top = next(c for c in A.root_cause(g, inc)["candidates"] if c["component_id"] == "lib:payments-sdk"); self.assertIn("outside", top["confidence_rationale"])

    def test_competing_hypotheses_lower_confidence(self):
        g = parsers.build([{"name": "m.json", "content": smap([N("a"), N("x"), N("y")], [E("a", "x"), E("a", "y")])}])[0]
        inc = parsers.parse_incident({"timestamp": "2026-01-02T00:00:00Z", "affected_component": "a", "events": [
            {"component": "x", "type": "change", "timestamp": "2026-01-01T23:00:00Z"}, {"component": "y", "type": "change", "timestamp": "2026-01-01T22:00:00Z"}]})
        rc = A.root_cause(g, inc); self.assertTrue(any("competing" in m for m in rc["candidates"][0]["missing_evidence"]))


class Counterfactual(unittest.TestCase):
    def test_immutability_hashes_and_delta(self):
        g, inc = demo(); h, n, e = g.hash(), len(g.nodes), len(g.edges); inc0 = copy.deepcopy(inc)
        r = A.counterfactual(g, inc, {"type": "remove_edge", "edge_id": next(k for k, v in g.edges.items() if v["source_node_id"] == "svc:notifier")})
        self.assertEqual((g.hash(), len(g.nodes), len(g.edges), inc), (h, n, e, inc0))
        self.assertEqual(r["baseline_graph_hash"], h); self.assertNotEqual(r["scenario_graph_hash"], h)
        self.assertEqual(r["status"], "OK"); self.assertTrue(r["assumptions"] and r["speculative"])
        r2 = A.counterfactual(g, inc, {"type": "remove_edge", "edge_id": next(k for k, v in g.edges.items() if v["source_node_id"] == "svc:notifier")})
        self.assertEqual(r["scenario_hash"], r2["scenario_hash"])

    def test_isolate_removes_downstream(self):
        g, inc = demo(); r = A.counterfactual(g, inc, {"type": "isolate_node", "node_id": "svc:checkout-api"})
        self.assertIn("svc:web-frontend", r["delta"]["affected_removed"]); self.assertEqual(r["delta"]["blast_level"][0], "CRITICAL")

    def test_remove_root_cause_changes_ranking_and_is_speculative(self):
        g, inc = demo(); r = A.counterfactual(g, inc, {"type": "remove_root_cause", "node_id": "lib:payments-sdk"})
        self.assertNotEqual(r["delta"]["root_cause_top"][1], "lib:payments-sdk"); self.assertTrue(any("NOT determined" in s for s in r["speculative"]))

    def test_upgrade_and_shift(self):
        g, inc = demo()
        self.assertEqual(A.counterfactual(g, inc, {"type": "upgrade_version", "node_id": "lib:payments-sdk", "new_version": "3.3.0"})["status"], "OK")
        self.assertEqual(g.nodes["lib:payments-sdk"]["version"], "3.2.0")
        self.assertEqual(A.counterfactual(g, inc, {"type": "shift_incident", "node_id": "svc:checkout-api"})["status"], "OK")

    def test_not_evaluable(self):
        g, inc = demo()
        for sc in ({"type": "remove_node", "node_id": "ghost"}, {"type": "remove_edge", "edge_id": "e:none"}, {"type": "wat"},
                   {"type": "upgrade_version", "node_id": "svc:auth", "new_version": "2"},      # no advisory data
                   {"type": "upgrade_version", "node_id": "svc:notifier", "new_version": "2"},  # unknown current version
                   {"type": "remove_node", "node_id": "svc:web-frontend"}, {"type": "shift_incident", "node_id": "svc:auth", "timestamp": "x"}):
            r = A.counterfactual(g, inc, sc); self.assertEqual(r["status"], "NOT_EVALUABLE", sc); self.assertTrue(r["reason"])


class ExportAndApi(unittest.TestCase):
    def test_export_json_markdown(self):
        g, inc = demo(); a = A.analyze(g, inc)
        j = json.loads(report.to_json(a)); self.assertEqual(j["schema_version"], "1.0"); self.assertTrue(j["analysis_id"].startswith("an-"))
        for k in ("known", "inferred", "unknown", "limitations", "graph_hash", "blast_radius", "root_cause"): self.assertIn(k, j)
        md = report.to_markdown(a); self.assertIn("Blast radius", md); self.assertIn("not proof", md)

    def test_router_flow_and_errors(self):
        self.assertEqual(server.handle("GET", "/api/v1/health", {})[0], 200)
        server.STATE.update(graph=None, incident=None)
        self.assertEqual(server.handle("GET", "/api/v1/graph", {})[1]["error"], "NO_GRAPH")
        self.assertEqual(server.handle("POST", "/api/v1/demo", {})[0], 200)
        self.assertEqual(server.handle("GET", "/api/v1/node/svc:auth", {})[0], 200)
        self.assertEqual(server.handle("GET", "/api/v1/node/zzz", {})[0], 404)
        self.assertEqual(server.handle("POST", "/api/v1/rca", {})[0], 200)
        st, p = server.handle("POST", "/api/v1/impact", {"node_id": "svc:auth"}); self.assertEqual(p["blast_radius"]["level"], "CRITICAL")
        self.assertEqual(server.handle("POST", "/api/v1/compare", {"scenario": {"type": "isolate_node", "node_id": "svc:auth"}})[1]["status"], "OK")
        self.assertIn("# Causal", server.handle("POST", "/api/v1/export", {"format": "markdown"})[1]["content"])
        self.assertEqual(server.handle("POST", "/api/v1/import", {"files": [{"name": "a.yaml", "content": "x"}]})[1]["error"], "UNSUPPORTED_FORMAT")
        self.assertEqual(server.handle("POST", "/api/v1/nope", {})[0], 404)

    def test_http_server_and_ui_sanitization(self):
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
            self.assertIn("Causal Impact Intelligence", html); self.assertIn("esc=s=>", html)    # escape helper present
            self.assertNotIn("innerHTML=n.name", html)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/demo", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            self.assertEqual(json.loads(urllib.request.urlopen(req).read())["status"], "OK")
            bad = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/import", data=b"{bad", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as c: urllib.request.urlopen(bad)
            self.assertEqual(c.exception.code, 400)
        finally: srv.shutdown()

    def test_malicious_names_are_data_not_markup(self):
        g = parsers.build([{"name": "m.json", "content": smap([N("a", name="<img src=x onerror=alert(1)>")], [])}])[0]
        self.assertIn("<img", g.nodes["a"]["name"])  # stored verbatim; UI escapes via esc() on every interpolation


if __name__ == "__main__":
    unittest.main(verbosity=1)

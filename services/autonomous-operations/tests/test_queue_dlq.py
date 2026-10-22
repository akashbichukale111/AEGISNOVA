import json
from helpers import *
from aegisnova_ops.engine import Refused
from aegisnova_ops.store import jdump


def dead_run(t):
    run = start(t.app, approval=False, simulate={"fail_times": 9, "kind": "transient"})
    for _ in range(6):
        t.e.tick(); t.clock.advance(10)
    assert status(t.app, run["id"]) == "DEAD_LETTERED"
    return run


class QueueTests(Base):
    def test_poison_malformed_payload_goes_to_dlq(self):
        mid = self.e.inject_raw_message("run_x", '{"run_id":"run_x","kind":"step","evil":1}')
        self.e.tick()
        d = self.s.one("SELECT * FROM dead_letters")
        self.assertEqual((d["error_class"], d["kind"]), ("poison", "queue_message"))
        self.assertEqual(self.s.one("SELECT status FROM queue_messages WHERE id=?", (mid,))["status"], "DEAD")

    def test_not_json_and_unknown_run_are_poison(self):
        self.e.inject_raw_message(None, "not json"); self.e.inject_raw_message("run_nope", '{"run_id":"run_nope","kind":"step"}')
        self.e.tick(); self.e.tick()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM dead_letters WHERE error_class='poison'")["c"], 2)

    def test_max_receive_count_dead_letters(self):
        run = start(self.app, approval=False)
        self.e.cfg.max_receive_count = 2
        for _ in range(3):
            self.e._claim(1); self.clock.advance(61)
        self.e._claim(1)
        d = self.s.one("SELECT * FROM dead_letters")
        self.assertEqual(d["error_class"], "max_receive_exceeded"); self.assertEqual(status(self.app, run["id"]), "DEAD_LETTERED")

    def test_transient_vs_permanent_classification(self):
        a = start(self.app, approval=False, simulate={"fail_times": 1, "kind": "transient"})
        b = start(self.app, approval=False, simulate={"fail_times": 1, "kind": "permanent"})
        self.e.tick()
        self.assertEqual(status(self.app, a["id"]), "RETRY_WAIT"); self.assertEqual(status(self.app, b["id"]), "FAILED")


class RedriveTests(Base):
    def test_dry_run_changes_nothing(self):
        run = dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        r = self.e.redrive([d["id"]], "admin", dry_run=True)
        self.assertTrue(r["plan"][0]["eligible"]); self.assertEqual(status(self.app, run["id"]), "DEAD_LETTERED")

    def test_redrive_requires_confirmation(self):
        dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        with self.assertRaises(Refused): self.e.redrive([d["id"]], "admin", dry_run=False, confirm=False)

    def test_redrive_preserves_identity_and_history(self):
        run = dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        msg_before = self.s.one("SELECT * FROM queue_messages WHERE id=?", (d["queue_message_id"],))
        self.s.x("UPDATE workflow_runs SET payload_json=payload_json WHERE id=?", (run["id"],))
        r = self.e.redrive([d["id"]], "admin-1", dry_run=False, confirm=True)
        self.assertEqual(r["redriven"], [d["id"]])
        msg = self.s.one("SELECT * FROM queue_messages WHERE id=?", (d["queue_message_id"],))
        self.assertEqual((msg["event_id"], msg["dedupe_key"]), (msg_before["event_id"], msg_before["dedupe_key"]))
        self.assertEqual(self.s.one("SELECT status FROM dead_letters")["status"], "REDRIVEN")
        self.assertEqual(status(self.app, run["id"]), "QUEUED")
        # history kept: earlier attempts still present; audit trail records actor
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM workflow_attempts")["c"], 3)
        self.assertTrue(self.s.one("SELECT 1 FROM events WHERE type='queue.redriven' AND actor='admin-1'"))
        self.assertTrue(self.s.one("SELECT 1 FROM events WHERE type='audit.dlq.redrive'"))
        # simulate failure cleared: next processing creates NEW attempts (still failing -> new DLQ record)
        for _ in range(6):
            self.e.tick(); self.clock.advance(10)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM workflow_attempts")["c"], 6)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM dead_letters")["c"], 2)

    def test_redrive_then_success_no_duplicate_effects(self):
        run = dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        p = json.loads(self.e.get_run(run["id"])["payload_json"]); p["simulate"]["fail_times"] = 0
        self.s.x("UPDATE workflow_runs SET payload_json=? WHERE id=?", (jdump(p), run["id"]))
        self.e.redrive([d["id"]], "a", dry_run=False, confirm=True); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)

    def test_caps_and_loop_guard(self):
        with self.assertRaises(Refused): self.e.redrive([f"d{i}" for i in range(11)], "a")
        dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        self.s.x("UPDATE dead_letters SET redrive_count=3 WHERE id=?", (d["id"],))
        plan = self.e.redrive([d["id"]], "a", dry_run=True)["plan"][0]
        self.assertFalse(plan["eligible"]); self.assertIn("loop", plan["reason"])
        self.e.cfg.redrive_max_per_hour = 0
        self.s.x("UPDATE dead_letters SET redrive_count=0 WHERE id=?", (d["id"],))
        with self.assertRaises(Refused): self.e.redrive([d["id"]], "a", dry_run=False, confirm=True)

    def test_poison_not_redrivable_and_unknown_id(self):
        self.e.inject_raw_message("run_x", "garbage"); self.e.tick()
        d = self.s.one("SELECT * FROM dead_letters")
        plan = self.e.redrive([d["id"], "missing"], "a", dry_run=True)["plan"]
        self.assertFalse(plan[0]["eligible"]); self.assertFalse(plan[1]["eligible"])

    def test_api_redrive_requires_admin_and_confirm(self):
        dead_run(self); d = self.s.one("SELECT * FROM dead_letters")
        self.assertEqual(call(self.app, "POST", "/api/dlq/redrive", "operator", {"ids": [d["id"]]})[0], 403)
        self.assertEqual(call(self.app, "POST", "/api/dlq/redrive", "admin", {"ids": [d["id"]], "dry_run": False})[0], 400)
        st, body = call(self.app, "POST", "/api/dlq/redrive", "admin", {"ids": [d["id"]], "dry_run": False, "confirm": True})
        self.assertEqual((st, len(body["redriven"])), (200, 1))
        st, body = call(self.app, "GET", f"/api/dlq/{d['id']}", "viewer"); self.assertEqual(st, 200)
        self.assertIn("attempt_history", body)

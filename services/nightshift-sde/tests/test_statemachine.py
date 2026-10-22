import unittest

from nightshift import statemachine as sm
from nightshift.errors import InvalidTransition


class StateMachineTests(unittest.TestCase):
    def test_every_state_defines_exits_and_targets_exist(self):
        self.assertEqual(set(sm.TRANSITIONS), set(sm.ALL_STATES))
        for frm, tos in sm.TRANSITIONS.items():
            self.assertTrue(tos <= set(sm.ALL_STATES), frm)

    def test_terminal_states_have_no_exits(self):
        for s in sm.TERMINAL:
            self.assertEqual(sm.TRANSITIONS[s], frozenset(), s)
            for target in sm.ALL_STATES:
                with self.assertRaises(InvalidTransition):
                    sm.validate(s, target)

    def test_invalid_transitions_rejected(self):
        for frm, to in [("CREATED", "EXECUTING"), ("QUEUED", "EXECUTING"), ("INSPECTING", "EXECUTING"), ("COMPLETED", "QUEUED"),
                        ("WAITING_FOR_APPROVAL", "EXECUTING"), ("RETRY_WAIT", "EXECUTING"), ("PAUSED", "EXECUTING"),
                        ("TESTING", "COMPLETED"), ("EXECUTING", "COMPLETED"), ("CANCEL_REQUESTED", "QUEUED"), ("FAILED", "QUEUED")]:
            with self.assertRaises(InvalidTransition, msg=f"{frm}->{to}"):
                sm.validate(frm, to)

    def test_unknown_state_rejected(self):
        with self.assertRaises(InvalidTransition):
            sm.validate("NOPE", "QUEUED")

    def test_write_capable_stage_only_reachable_through_the_gate(self):
        # The invariant that protects the repository: EXECUTING is entered ONLY from READY_TO_EXECUTE.
        entering = [s for s, tos in sm.TRANSITIONS.items() if sm.EXECUTING in tos]
        self.assertEqual(entering, [sm.READY_TO_EXECUTE])
        self.assertEqual([s for s, tos in sm.TRANSITIONS.items() if sm.TESTING in tos], [sm.EXECUTING])
        self.assertEqual([s for s, tos in sm.TRANSITIONS.items() if sm.INDEPENDENT_VERIFICATION in tos], [sm.TESTING])

    def test_only_verification_stage_can_complete_a_repair_path(self):
        # A repair can only COMPLETE from INDEPENDENT_VERIFICATION (or via the gate with an explicit non-repair outcome).
        completing = {s for s, tos in sm.TRANSITIONS.items() if sm.COMPLETED in tos}
        self.assertEqual(completing, {sm.RISK_ASSESSMENT, sm.INDEPENDENT_VERIFICATION})
        self.assertNotIn(sm.COMPLETED, sm.TRANSITIONS[sm.EXECUTING])
        self.assertNotIn(sm.COMPLETED, sm.TRANSITIONS[sm.TESTING])

    def test_resume_state_always_regates_write_work(self):
        for stage in ("proposal", "ready", "execute", "test", "verify"):
            self.assertEqual(sm.RESUME_STATE[stage], sm.READY_TO_EXECUTE)

    def test_waiting_is_distinct_from_active(self):
        self.assertTrue(sm.WAITING.isdisjoint(sm.ACTIVE))
        self.assertTrue(sm.TERMINAL.isdisjoint(sm.LEASE_HOLDING))


if __name__ == "__main__":
    unittest.main()

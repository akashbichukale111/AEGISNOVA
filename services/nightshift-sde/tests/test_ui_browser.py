"""Real-browser tests of critical console interactions (skipped when Playwright/Chromium is unavailable).
Runs the real HTTP server against a temp database with synthetic TEST DATA fixtures."""
import os
import threading
import unittest

try:
    from playwright.sync_api import sync_playwright
    HAVE = True
except Exception:  # noqa: BLE001
    HAVE = False

from tests.helpers import Env
from nightshift.server import create_server

CHROMIUM = os.environ.get("NIGHTSHIFT_TEST_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)


@unittest.skipUnless(HAVE, "playwright not installed")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.srv = create_server(cls.env.app, "127.0.0.1", 0)
        cls.url = "http://127.0.0.1:%d/" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"]) if CHROMIUM else cls.pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            cls.pw.stop(); cls.srv.shutdown()
            raise unittest.SkipTest(f"no chromium: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.srv.shutdown(); cls.env.tmp.cleanup()

    def page(self, role="admin"):
        pg = self.browser.new_page(viewport={"width": 1400, "height": 900})
        self.errors = []
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        pg.on("console", lambda m: self.errors.append(m.text) if m.type == "error" and "401" not in m.text else None)
        pg.goto(self.url)
        if role:
            pg.fill("#tok", self.env.settings_token(role) if hasattr(self.env, "settings_token") else {"admin": "test-admin-token-not-a-secret", "viewer": "test-viewer-token-not-a-secret", "operator": "test-operator-token-not-a-secret"}[role])
            pg.click("button[type=submit]")
            pg.wait_for_selector(".kpis")
        return pg

    def test_bad_token_rejected_and_no_data_shown(self):
        pg = self.page(role=None)
        pg.fill("#tok", "nope"); pg.click("button[type=submit]")
        pg.wait_for_selector(".err:has-text('not accepted')")
        self.assertEqual(pg.locator(".kpis").count(), 0)
        pg.close()

    def test_command_center_renders_real_zero_state_without_fabricated_jobs(self):
        pg = self.page()
        self.assertIn("Local mode", pg.inner_text(".mode"))
        self.assertIn("No jobs are running", pg.inner_text("main"))
        self.assertEqual(self.errors, [])
        pg.close()

    def test_all_routes_render_without_errors_and_keyboard_nav(self):
        pg = self.page()
        for route in ("jobs", "schedules", "fleet", "dependencies", "recovery", "audit", "settings"):
            pg.goto(self.url + "#/" + route)
            pg.wait_for_selector("main .panel, main .grid, main .errbox", timeout=10000)
            pg.wait_for_selector("main .loading", state="detached")
            self.assertEqual(pg.locator("main .errbox").count(), 0, route)
        pg.goto(self.url + "#/")
        pg.focus("nav a.item >> nth=1"); pg.keyboard.press("Enter")
        pg.wait_for_url("**/#/jobs")
        self.assertEqual(self.errors, [])
        pg.close()

    def test_trigger_inspection_through_ui_creates_real_job_and_is_idempotent_per_click(self):
        pg = self.page()
        pg.goto(self.url + "#/fleet"); pg.wait_for_selector("text=Run inspection")
        before = self.env.app._q1("SELECT COUNT(*) n FROM jobs")["n"]
        pg.locator("button:has-text('Run inspection')").first.click()
        pg.locator("dialog button:has-text('Trigger')").click()
        pg.wait_for_url("**/#/jobs/*")
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) n FROM jobs")["n"], before + 1)
        pg.wait_for_selector(".tl")  # state-machine timeline from persisted transitions
        self.assertIn("QUEUED".capitalize(), pg.inner_text(".tl"))
        pg.close()

    def test_viewer_sees_disabled_controls_with_reasons(self):
        pg = self.page("viewer")
        pg.goto(self.url + "#/fleet"); pg.wait_for_selector("text=Run inspection")
        b = pg.locator("button:has-text('Run inspection')").first
        self.assertTrue(b.is_disabled())
        self.assertIn("requires operator", b.inner_text())
        pg.close()

    def test_schedule_studio_server_validation_error_is_shown(self):
        pg = self.page()
        pg.goto(self.url + "#/schedules"); pg.wait_for_selector("text=New schedule")
        pg.click("button:has-text('New schedule')")
        pg.wait_for_selector("form.panel")
        pg.locator("form.panel input").first.fill("bad tz schedule")
        pg.locator("input[list=tzs]").fill("Mars/Olympus")
        pg.wait_for_selector(".note.bad:has-text('timezone')", timeout=5000)
        pg.close()

    def test_schedule_create_then_pause_through_ui(self):
        pg = self.page()
        pg.goto(self.url + "#/schedules"); pg.wait_for_selector("text=New schedule")
        pg.click("button:has-text('New schedule')"); pg.wait_for_selector("form.panel")
        pg.locator("form.panel input").first.fill("ui nightly")
        pg.click("button:has-text('Create schedule')")
        pg.wait_for_selector("td:has-text('ui nightly')")
        pg.locator("tr:has-text('ui nightly') button:has-text('Pause')").click()
        pg.wait_for_selector("tr:has-text('ui nightly') .pill:has-text('Paused')")
        self.assertEqual(self.env.app._q1("SELECT status FROM schedules WHERE name='ui nightly'")["status"], "paused")
        pg.close()


if __name__ == "__main__":
    unittest.main()

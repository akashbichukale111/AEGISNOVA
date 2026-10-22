"""Static guarantees about the console: served, CSP-safe (no inline script/style, no innerHTML), and no external requests."""
import re
import unittest
from pathlib import Path


UI = Path(__file__).resolve().parent.parent / "ui"


class UiStaticTests(unittest.TestCase):
    def test_no_inline_script_or_style_in_html(self):
        html = (UI / "index.html").read_text()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotIn("<style", html)
        self.assertNotRegex(html, r'\sstyle=')
        self.assertNotRegex(html, r'\son\w+=')

    def test_no_innerhtml_or_eval_in_js(self):
        for f in UI.rglob("*.js"):
            src = f.read_text()
            for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write"):
                self.assertNotIn(bad, src, f"{f.name} uses {bad}")

    def test_no_external_urls(self):
        for f in list(UI.rglob("*.js")) + list(UI.rglob("*.css")) + [UI / "index.html"]:
            for m in re.findall(r"https?://[^\s\"')]+", f.read_text()):
                if m == "http://www.w3.org/2000/svg":  # SVG XML namespace identifier, not a network request
                    continue
                self.fail(f"{f.name} references external URL {m}")

    def test_expected_views_exist(self):
        for v in ("overview", "jobs", "schedules", "fleet", "deps", "recovery", "audit", "settings"):
            self.assertTrue((UI / "views" / f"{v}.js").is_file(), v)


if __name__ == "__main__":
    unittest.main()

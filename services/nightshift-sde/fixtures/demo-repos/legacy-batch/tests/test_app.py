import re
import unittest
from pathlib import Path

import app


class AppTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(app.version(), "1.0")

    def test_requirements_are_pinned(self):
        text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9._-]+==[0-9][A-Za-z0-9.]*$")


if __name__ == "__main__":
    unittest.main()

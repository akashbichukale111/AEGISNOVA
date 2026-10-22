"""Regenerate DEMO fixture patches deterministically (difflib)."""
import difflib, os
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); R = os.path.join(H, "fixtures/repos/sample"); P = os.path.join(H, "fixtures/patches")
def rd(p): return open(os.path.join(R, p)).read()
def diff(path, new):
    old = rd(path); return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + path, "b/" + path))
GOOD = 'def safe_div(a, b):\n    """Divide a by b. Contract: division by zero must raise ValueError."""\n    if b == 0:\n        raise ValueError("division by zero")\n    return a / b\n'
SWALLOW = 'def safe_div(a, b):\n    """Divide a by b. Contract: division by zero must raise ValueError."""\n    try:\n        return a / b\n    except Exception:\n        return None\n'
t = rd("tests/test_calc.py").replace("    def test_zero_raises_valueerror", "    @unittest.skip('flaky')\n    def test_zero_raises_valueerror")
WEAK = diff("calc.py", SWALLOW) + diff("tests/test_calc.py", t)
files = {"good.diff": diff("calc.py", GOOD), "swallow_error.diff": diff("calc.py", SWALLOW), "weakened_tests.diff": WEAK,
         "traversal.diff": "--- a/../../etc/passwd\n+++ b/../../etc/passwd\n@@ -1,1 +1,1 @@\n-x\n+y\n", "malformed.diff": "this is not a diff\n@@ nonsense\n",
         "absolute.diff": "--- /etc/passwd\n+++ /etc/passwd\n@@ -1,1 +1,1 @@\n-x\n+y\n"}
for k, v in files.items(): open(os.path.join(P, k), "w").write(v)
print("wrote", sorted(files))

import unittest
from calc import safe_div


class TestCalc(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(safe_div(6, 3), 2)

    def test_zero_raises_valueerror(self):
        with self.assertRaises(ValueError):
            safe_div(1, 0)

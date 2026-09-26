import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class Greet(unittest.TestCase):
    def test_greet_function(self):
        sys.path.insert(0, str(REPO))
        import greet
        self.assertEqual(greet.greet("Ada"), "Hello, Ada!")

    def test_cli_runs(self):
        out = subprocess.run([sys.executable, "greet.py", "Ada"],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Hello, Ada!", out.stdout)


if __name__ == "__main__":
    unittest.main()

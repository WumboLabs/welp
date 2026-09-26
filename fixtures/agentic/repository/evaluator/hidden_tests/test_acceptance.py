"""Hidden acceptance tests (evaluator-only) for the notes CLI.

CLI/behavior-level only: a valid fix may use any internal structure.
Encodes the README consumer contract and the REVIEW.md reviewer feedback.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_cli(*argv, cwd):
    return subprocess.run([sys.executable, str(REPO / "notes.py"), *argv],
                          cwd=cwd, capture_output=True, text=True)


class EmptyStoreJsonContract(unittest.TestCase):
    def test_list_json_empty_store_keeps_items_key(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_cli("list", "--json", cwd=td)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), {"items": []})

    def test_list_empty_store_text_rc0(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_cli("list", cwd=td)
            self.assertEqual(out.returncode, 0, out.stderr)


class JsonOrderingContract(unittest.TestCase):
    def test_list_json_sorted_and_shaped(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_cli("add", "low-task", "--priority", "low", cwd=td).returncode, 0)
            self.assertEqual(run_cli("add", "high-task", "--priority", "high", cwd=td).returncode, 0)
            self.assertEqual(run_cli("add", "normal-task", "--priority", "normal", cwd=td).returncode, 0)
            self.assertEqual(run_cli("done", "1", cwd=td).returncode, 0)
            out = run_cli("list", "--json", cwd=td)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(out.stdout)
            self.assertIn("items", data)
            self.assertEqual([n["id"] for n in data["items"]], [2, 3, 1])


class InterfaceUnchanged(unittest.TestCase):
    def test_help_lists_documented_commands(self):
        out = run_cli("--help", cwd=REPO)
        self.assertEqual(out.returncode, 0, out.stderr)
        for cmd in ("add", "list", "done"):
            self.assertIn(cmd, out.stdout)

    def test_list_json_argument_intact(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_cli("list", "--json", cwd=td)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_priority_argument_intact(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_cli("add", "t", "--priority", "high", cwd=td)
            self.assertEqual(out.returncode, 0, out.stderr)
            store = json.loads((Path(td) / "store.json").read_text())
            self.assertEqual(store[0]["priority"], "high")

    def test_done_missing_id_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_cli("add", "x", cwd=td).returncode, 0)
            out = run_cli("done", "99", cwd=td)
            self.assertNotEqual(out.returncode, 0)


if __name__ == "__main__":
    unittest.main()

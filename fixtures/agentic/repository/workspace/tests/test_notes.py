"""Visible tests for the notes CLI fixture (initially failing)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import notes  # noqa: E402


def run_cli(*argv, cwd):
    return subprocess.run([sys.executable, str(REPO / "notes.py"), *argv],
                          cwd=cwd, capture_output=True, text=True)


class LoadNotes(unittest.TestCase):
    def test_missing_store_is_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            notes.STORE = Path(td) / "store.json"
            try:
                self.assertEqual(notes.load_notes(), [])
            finally:
                notes.STORE = Path("store.json")

    def test_empty_store_file_is_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "store.json"
            p.write_text("")
            notes.STORE = p
            try:
                self.assertEqual(notes.load_notes(), [])
            finally:
                notes.STORE = Path("store.json")


class ListingOrder(unittest.TestCase):
    def test_pending_before_done_then_priority_then_id(self):
        seq = [
            {"id": 1, "text": "low-task", "priority": "low", "done": False},
            {"id": 2, "text": "high-task", "priority": "high", "done": False},
            {"id": 3, "text": "finished", "priority": "high", "done": True},
            {"id": 4, "text": "normal-task", "priority": "normal", "done": False},
        ]
        got = _list_text_order(seq)
        self.assertEqual(got, [2, 4, 1, 3])


def _list_text_order(seq):
    """Rendered order of `notes.py list` for a given store, as id list."""
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "store.json").write_text(json.dumps(seq))
        out = run_cli("list", cwd=td)
        if out.returncode != 0:
            raise AssertionError(f"list failed rc={out.returncode}: {out.stderr}")
        ids = [int(line.split("]")[1].strip().split(" ")[0])
               for line in out.stdout.splitlines() if line.startswith("[")]
        return ids


class CliStillWorks(unittest.TestCase):
    def test_add_then_done_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_cli("add", "hello", cwd=td).returncode, 0)
            self.assertEqual(run_cli("done", "1", cwd=td).returncode, 0)
            store = json.loads((Path(td) / "store.json").read_text())
            self.assertTrue(store[0]["done"])


if __name__ == "__main__":
    unittest.main()

import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import queue as app
class Visible(unittest.TestCase):
    def test_missing(self):
        with tempfile.TemporaryDirectory() as d:
            old=app.STORE;app.STORE=Path(d)/'queue.json'
            try:self.assertEqual(app.load_jobs(),[])
            finally:app.STORE=old
    def test_empty(self):
        with tempfile.TemporaryDirectory() as d:
            old=app.STORE;app.STORE=Path(d)/'queue.json';app.STORE.write_text('  ')
            try:self.assertEqual(app.load_jobs(),[])
            finally:app.STORE=old
    def test_order(self):
        jobs=[dict(ticket=9,priority='normal',done=True),dict(ticket=8,priority='low',done=False),dict(ticket=4,priority='high',done=False),dict(ticket=2,priority='high',done=False)]
        self.assertEqual([j['ticket'] for j in app.ordered(jobs)],[4,2,8,9])
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'queue.json').write_text('[]')
            for args in [('add','crate'),('done','1')]:
                p=subprocess.run([sys.executable,str(ROOT/'queue.py'),*args],cwd=d,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(json.loads(Path(d,'queue.json').read_text())[0]['done'])

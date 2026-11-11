import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path('/workspace')
def call(*args,cwd):
    return subprocess.run([sys.executable,str(ROOT/'queue.py'),*args],cwd=cwd,capture_output=True,text=True)
class Acceptance(unittest.TestCase):
    def test_empty_envelope(self):
        with tempfile.TemporaryDirectory() as d:
            p=call('list','--json',cwd=d);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout),dict(jobs=[]))
    def test_empty_text(self):
        with tempfile.TemporaryDirectory() as d:
            p=call('list',cwd=d);self.assertEqual((p.returncode,p.stdout),(0,''))
    def test_nonempty_order(self):
        with tempfile.TemporaryDirectory() as d:
            seq=[dict(ticket=7,label='first',priority='normal',done=False),dict(ticket=5,label='other',priority='high',done=True),dict(ticket=3,label='urgent',priority='high',done=False),dict(ticket=1,label='second',priority='normal',done=False)]
            Path(d,'queue.json').write_text(json.dumps(seq))
            p=call('list','--json',cwd=d);self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual([j['ticket'] for j in json.loads(p.stdout)['jobs']],[3,7,1,5])
            self.assertEqual(json.loads(Path(d,'queue.json').read_text()),seq)
    def test_help(self):
        p=call('--help',cwd=ROOT);self.assertEqual(p.returncode,0)
        for cmd in ('add','list','done'):self.assertIn(cmd,p.stdout)
    def test_json_switch(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'queue.json').write_text('[]');p=call('list','--json',cwd=d)
            self.assertEqual(p.returncode,0);self.assertEqual(set(json.loads(p.stdout)),{'jobs'})
    def test_priority_switch(self):
        with tempfile.TemporaryDirectory() as d:
            p=call('add','fragile','--priority','high',cwd=d);self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(Path(d,'queue.json').read_text())[0]['priority'],'high')
    def test_unknown_done(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'queue.json').write_text('[]');self.assertNotEqual(call('done','404',cwd=d).returncode,0)

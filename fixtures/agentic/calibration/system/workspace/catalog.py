import json,logging
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
cfg=json.loads(Path('config/catalog.json').read_text())
logging.basicConfig(level=cfg['log_level'].upper())
rows=json.loads(Path(cfg['data_file']).read_text())
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/health':self.send_error(404);return
        out=json.dumps(dict(status='ok',records=len(rows))).encode()
        self.send_response(200);self.end_headers();self.wfile.write(out)
HTTPServer(('127.0.0.1',cfg['port']),Handler).serve_forever()

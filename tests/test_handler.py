# Test des Handlers gegen einen simulierten ComfyUI-Server:  python runpod-worker/tests/test_handler.py
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
base = Path(tempfile.mkdtemp()) / "comfy"
os.environ["COMFY_DIR"] = str(base); os.environ["COMFY_HOST"] = "127.0.0.1:18188"
(base/"output").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import handler as h
store = {}
class S(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/system_stats": return self._send(200, b"{}")
        if self.path.startswith("/history/"):
            pid = self.path.split("/")[-1]
            if time.time() - store["t"] < 1: return self._send(200, b"{}")
            (base/"output"/"vids").mkdir(exist_ok=True)
            (base/"output"/"vids"/"out_00001.mp4").write_bytes(b"VIDEO"*100)
            (base/"output"/"prev.png").write_bytes(b"PNG")
            out = {pid: {"status": {"status_str": "success", "completed": True}, "outputs": {
                "9": {"images": [{"filename": "prev.png", "subfolder": "", "type": "output"}]},
                "14": {"gifs": [{"filename": "out_00001.mp4", "subfolder": "vids", "type": "output", "fullpath": str(base/"output"/"vids"/"out_00001.mp4")}]}}}}
            return self._send(200, json.dumps(out).encode())
        if self.path == "/file/in.mp4": return self._send(200, b"INPUTVIDEO", "video/mp4")
        self._send(404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n))
        assert "prompt" in body; store["t"] = time.time(); store["wf"] = body["prompt"]
        self._send(200, json.dumps({"prompt_id": "p1", "node_errors": {}}).encode())
    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0)); store[self.path] = self.rfile.read(n); self._send(200)
srv = ThreadingHTTPServer(("127.0.0.1", 18188), S); threading.Thread(target=srv.serve_forever, daemon=True).start()
h.runpod.serverless.progress_update = lambda job, msg: None
res = h.handler({"id": "j", "input": {"workflow": {"1": {"class_type": "X", "inputs": {}}},
   "inputs": [{"name": "in.mp4", "url": "http://127.0.0.1:18188/file/in.mp4"}],
   "uploads": [{"slot": 0, "url": "http://127.0.0.1:18188/put/0"}, {"slot": 1, "url": "http://127.0.0.1:18188/put/1"}], "prefer": "video"}})
print(res)
assert res["files"][0]["name"] == "out_00001.mp4" and store["/put/0"] == b"VIDEO"*100
assert not (base/"input"/"in.mp4").exists() and not any((base/"output").iterdir())
print("OK")

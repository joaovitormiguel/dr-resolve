#!/usr/bin/env python3
"""Local web UI for Resolve. Run:  python3 app.py   then open http://localhost:8765

No dependencies beyond resolve.py's (Pillow, numpy, ffmpeg). Files stay on your machine:
uploads land in ./jobs/<id>/in, results in ./jobs/<id>/out.
"""
import json, re, subprocess, sys, threading, time, uuid, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
JOBS = HERE / "jobs"; JOBS.mkdir(exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
jobs = {}  # id -> {status, log, files, started}

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resolve</title>
<style>
:root{--bg:#000;--surface:#111;--border:#262626;--text:#E5E7EB;--muted:#9CA3AF;--lime:#CDFE7C}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,"DM Sans",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}h1{font-size:28px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 28px}
.grid{display:grid;grid-template-columns:360px 1fr;gap:24px}@media(max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px}
label{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:14px 0 6px;font-family:ui-monospace,"JetBrains Mono",monospace}
input,select{width:100%;background:#000;border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px 10px;font:inherit}
input[type=file]{padding:8px}input[type=range]{padding:0}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.val{color:var(--lime);font-family:ui-monospace,monospace;font-size:12px;margin-left:6px}
button{width:100%;margin-top:22px;background:var(--lime);color:#000;border:0;border-radius:8px;padding:12px;font:600 15px inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}.drop{border:1px dashed var(--border);border-radius:10px;padding:18px;text-align:center;color:var(--muted);cursor:pointer}
.drop.on{border-color:var(--lime);color:var(--text)}.status{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);white-space:pre-wrap;margin-top:12px}
.out{display:grid;gap:16px}.out figure{margin:0}.out img,.out video{width:100%;border-radius:10px;border:1px solid var(--border);background:#000;display:block}
.out figcaption{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--muted);margin-top:6px}
.out a{color:var(--lime);text-decoration:none}.hint{font-size:12px;color:var(--muted);margin-top:6px}.hidden{display:none}
.tag{display:inline-block;border:1px solid var(--border);border-radius:999px;padding:1px 8px;font-family:ui-monospace,monospace;font-size:11px;color:var(--lime)}
</style></head><body><main>
<h1>Resolve</h1><p class="sub">Field → dither → clear. Drop an image or video, pick a state, render.</p>
<div class="grid"><form class="card" id="f">
<div class="drop" id="drop">Drop a file here or click to choose<br><span id="fname" class="tag hidden"></span></div>
<input type="file" id="file" name="file" accept="image/*,video/*" class="hidden" required>
<label>State</label><select name="state" id="state"><option value="all">All three stills (field, dither, clear)</option><option value="sequence">Sequence: field → dither → clear</option><option value="field">Field only</option><option value="dither">Dither only</option><option value="clear">Clear only</option></select>
<label>Output width <span class="val" id="widthv">source</span></label><input type="number" name="width" id="width" placeholder="source width" min="240" step="2">
<div class="row"><div><label>Field columns <span class="val" id="colsv">72</span></label><input type="range" name="cols" id="cols" min="24" max="160" value="72"></div>
<div><label>Dither block px <span class="val" id="blockv">12</span></label><input type="range" name="block" id="block" min="4" max="32" value="12"></div></div>
<div class="row"><div><label>Dither levels <span class="val" id="levelsv">4</span></label><input type="range" name="levels" id="levels" min="2" max="8" value="4"></div>
<div><label>Field reroll <span class="val" id="rerollv">0.05</span></label><input type="range" name="reroll" id="reroll" min="0" max="0.3" step="0.01" value="0.05"></div></div>
<div id="seqimg"><div class="row"><div><label>Length (s)</label><input type="number" name="seconds" value="4" step="0.5" min="1"></div><div><label>Hold clear (s)</label><input type="number" name="hold" value="1" step="0.5" min="0"></div></div></div>
<div id="seqvid" class="hidden"><div class="row"><div><label>Resolve starts (s)</label><input type="number" name="start" value="1" step="0.5" min="0"></div><div><label>Fully clear by (s)</label><input type="number" name="end" value="5" step="0.5" min="0"></div></div><div class="hint">Before "start" the clip is pure field; after "end" it is the clean source.</div></div>
<label>FPS</label><input type="number" name="fps" value="24" min="12" max="60">
<button id="go">Render</button><div class="status" id="status"></div></form>
<div class="card"><div class="out" id="out"><p class="hint">Results appear here. Subjects that fill the frame against dark backgrounds resolve best; a small object in a mid-gray scene reads as noise.</p></div></div></div></main>
<script>
const $=s=>document.querySelector(s);const file=$('#file'),drop=$('#drop'),fname=$('#fname');
drop.onclick=()=>file.click();['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('on')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('on')}));
drop.addEventListener('drop',ev=>{file.files=ev.dataTransfer.files;showName()});file.onchange=showName;
function isVideo(){const f=file.files[0];return f&&(f.type.startsWith('video')||/\.(mp4|mov|webm|m4v)$/i.test(f.name))}
function showName(){const f=file.files[0];if(!f)return;fname.textContent=f.name;fname.classList.remove('hidden');syncSeq()}
function syncSeq(){const seq=$('#state').value==='sequence';$('#seqimg').classList.toggle('hidden',!(seq&&!isVideo()));$('#seqvid').classList.toggle('hidden',!(seq&&isVideo()))}
$('#state').onchange=syncSeq;
for(const id of['cols','block','levels','reroll']){const el=$('#'+id);el.oninput=()=>$('#'+id+'v').textContent=el.value}
$('#width').oninput=e=>$('#widthv').textContent=e.target.value||'source';
$('#f').onsubmit=async ev=>{ev.preventDefault();if(!file.files[0]){alert('Choose a file first');return}
$('#go').disabled=true;$('#status').textContent='Uploading…';$('#out').innerHTML='';
const fd=new FormData($('#f'));const r=await fetch('/render',{method:'POST',body:fd});const {id}=await r.json();
const poll=async()=>{const s=await (await fetch('/status?id='+id)).json();$('#status').textContent=s.log;
if(s.status==='done'){$('#go').disabled=false;render(id,s.files)}else if(s.status==='error'){$('#go').disabled=false}else setTimeout(poll,1500)};poll()};
function render(id,files){const out=$('#out');out.innerHTML='';for(const f of files){const url='/jobs/'+id+'/out/'+encodeURIComponent(f);const fig=document.createElement('figure');
const isv=/\.mp4$/i.test(f);fig.innerHTML=(isv?`<video src="${url}" controls autoplay loop muted playsinline></video>`:`<img src="${url}">`)+`<figcaption><span>${f}</span><a href="${url}" download>Download</a></figcaption>`;out.appendChild(fig)}}
</script></body></html>"""

def parse_multipart(body, ctype):
    boundary = re.search(r'boundary=("?)([^";]+)\1', ctype).group(2).encode()
    fields, files = {}, {}
    for part in body.split(b"--" + boundary)[1:]:
        if part.strip() in (b"", b"--"): continue
        head, _, data = part.partition(b"\r\n\r\n"); data = data[:-2] if data.endswith(b"\r\n") else data
        disp = re.search(rb'name="([^"]+)"', head); name = disp.group(1).decode() if disp else None
        fn = re.search(rb'filename="([^"]*)"', head)
        if fn and fn.group(1): files[name] = (Path(fn.group(1).decode()).name, data)
        elif name: fields[name] = data.decode(errors="replace")
    return fields, files

def run_job(jid, fields, filename, data):
    job = jobs[jid]; d = JOBS / jid; (d / "in").mkdir(parents=True); (d / "out").mkdir()
    src = d / "in" / filename; src.write_bytes(data)
    is_video = src.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}
    cmd = [sys.executable, str(HERE / "resolve.py"), str(src), str(d / "out"), "--state", fields.get("state", "all")]
    for k in ("cols", "block", "levels", "fps", "reroll"):
        if fields.get(k): cmd += [f"--{k}", fields[k]]
    if fields.get("width"): cmd += ["--width", fields["width"]]
    if fields.get("state") == "sequence":
        if is_video:
            for k in ("start", "end"):
                if fields.get(k): cmd += [f"--{k}", fields[k]]
        else:
            for k in ("seconds", "hold"):
                if fields.get(k): cmd += [f"--{k}", fields[k]]
    job["log"] = "Rendering… " + ("(video: this can take a few minutes)" if is_video else "")
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        job["status"] = "error"; job["log"] = "Render failed:\n" + (p.stderr or p.stdout)[-2000:]; return
    order = ["field", "dither", "clear", "resolve"]
    files = sorted((f.name for f in (d / "out").iterdir()), key=lambda n: next((i for i, s in enumerate(order) if f"-{s}." in n), 9))
    job["files"] = files; job["status"] = "done"; job["log"] = f"Done in {time.time() - job['started']:.0f}s. " + p.stdout.strip()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/": return self.send(200, PAGE.encode())
        if u.path == "/status":
            j = jobs.get(parse_qs(u.query).get("id", [""])[0]); return self.send(200, json.dumps(j or {"status": "error", "log": "unknown job"}).encode(), "application/json")
        if u.path.startswith("/jobs/"):
            p = (HERE / u.path.lstrip("/")).resolve()
            if not str(p).startswith(str(JOBS)) or not p.is_file(): return self.send(404, b"not found", "text/plain")
            ext = p.suffix.lower(); ctype = {"png": "image/png", "jpg": "image/jpeg", "mp4": "video/mp4"}.get(ext[1:], "application/octet-stream")
            data = p.read_bytes(); self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self.send(404, b"not found", "text/plain")
    def do_POST(self):
        if urlparse(self.path).path != "/render": return self.send(404, b"not found", "text/plain")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        fields, files = parse_multipart(body, self.headers.get("Content-Type", ""))
        if "file" not in files: return self.send(400, b'{"error":"no file"}', "application/json")
        jid = uuid.uuid4().hex[:8]; jobs[jid] = {"status": "running", "log": "Queued", "files": [], "started": time.time()}
        threading.Thread(target=run_job, args=(jid, fields, *files["file"]), daemon=True).start()
        self.send(200, json.dumps({"id": jid}).encode(), "application/json")

if __name__ == "__main__":
    print(f"Resolve UI at http://localhost:{PORT}  (Ctrl+C to stop)")
    threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()

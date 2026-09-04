#!/usr/bin/env python3
"""Dependency-light local correction UI for DadHandwriting.ttf."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
import handwriting_font as hf

ROOT=Path(__file__).resolve().parent; HOST,PORT="127.0.0.1",8765
class Handler(BaseHTTPRequestHandler):
    def send(self,status=200,kind="application/json",body=b""):
        self.send_response(status); self.send_header("Content-Type",kind); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/": return self.send(200,"text/html; charset=utf-8",(ROOT/"ui/index.html").read_bytes())
        if p=="/scan.png": return self.send(200,"image/png",hf.SCAN.read_bytes())
        if p=="/font.ttf" and hf.OUTPUT.exists(): return self.send(200,"font/ttf",hf.OUTPUT.read_bytes())
        if p=="/api/samples": return self.send(body=json.dumps(hf.load_samples(),ensure_ascii=False).encode())
        if p=="/api/settings": return self.send(body=json.dumps(hf.load_settings(),ensure_ascii=False).encode())
        if p=="/api/meta":
            from PIL import Image
            width,height=Image.open(hf.SCAN).size
            return self.send(body=json.dumps({"width":width,"height":height}).encode())
        return self.send(404,"text/plain",b"Not found")
    def do_POST(self):
        p=urlparse(self.path).path
        try:
            length=int(self.headers.get("Content-Length",0))
            if p=="/api/upload":
                if length>25*1024*1024: raise ValueError("Upload exceeds 25 MB")
                name=unquote(self.headers.get("X-Filename","upload"))
                result=hf.import_document(self.rfile.read(length),name)
                return self.send(body=json.dumps(result,ensure_ascii=False).encode())
            data=json.loads(self.rfile.read(length) or b"null")
            if p=="/api/samples":
                if not isinstance(data,list): raise ValueError("Expected a sample list")
                hf.save_samples(data); result={"ok":True}
            elif p=="/api/settings":
                if not isinstance(data,dict): raise ValueError("Expected settings")
                hf.save_settings(data); result={"ok":True}
            elif p=="/api/build":
                if isinstance(data,list): hf.save_samples(data)
                else:
                    hf.save_samples(data["samples"]); hf.save_settings(data["settings"])
                result=hf.build_font()
            else: result=None
            if result is None: return self.send(404,"text/plain",b"Not found")
            return self.send(body=json.dumps(result,ensure_ascii=False).encode())
        except Exception as exc: return self.send(500,body=json.dumps({"error":str(exc)}).encode())
    def log_message(self,fmt,*args): print(fmt%args)
def main():
    hf.prepare(); hf.load_samples(); hf.load_settings(); print(f"Open http://{HOST}:{PORT} in your browser (Ctrl+C to stop)"); ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()

"""Local-only synthetic BFF for the mobile AI Browser workspace prototype.

Loopback only, no production accounts, credentials, browser automation or Steel.
The backend intentionally proves protocol behavior, NOT tenant authentication.
Never publish this demo server to the public internet.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import secrets
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"workspace_broker"))
from broker import Broker,Principal,Workspace,BrokerError

STATIC=ROOT/"ux"/"mobile"
JS=pathlib.Path(__file__).with_name("demo_connected.js")
HOSTS=frozenset({"business.facebook.com","www.facebook.com",
                 "www.instagram.com","www.google.com","github.com",
                 "example.com","example.net"})

class MockAdapter:
    def __init__(self):
        self.current=[]
        self.count=0
    async def sessions(self):
        return [dict(x) for x in self.current]
    async def start(self,profile,url,mode):
        if self.current:raise RuntimeError("SIMULATED_OTHER_SESSION")
        if mode!="read_only":raise RuntimeError("WRITE_MODE_DISABLED")
        self.count+=1
        result={"session_id":"fake-remote-"+secrets.token_hex(10),
                "profile":profile,"mode":"read_only"}
        self.current=[result]
        return {"session_id":result["session_id"]}
    async def new_tab(self,session_id,url):
        if not self.current or self.current[0]["session_id"]!=session_id:
            return {"ok":False}
        return {"ok":True}
    async def stop(self,session_id):
        if not self.current or self.current[0]["session_id"]!=session_id:
            return {"profile_saved":False,"full_profile_saved":False}
        self.current.clear()
        return {"profile_saved":True,"full_profile_saved":True}

def demo_broker():
    adapter=MockAdapter()
    ws=[
        Workspace("demo-tenant","clinic","Synthetic - Clinic",HOSTS),
        Workspace("demo-tenant","architect","Synthetic - Architect",HOSTS),
        Workspace("demo-tenant","demo","Synthetic - Test",HOSTS),
    ]
    return Broker(adapter,ws,max_queue=12,max_tabs=12),adapter

def principal(workspace_id):
    if workspace_id not in ("clinic","architect","demo"):
        raise BrokerError("WORKSPACE_NOT_FOUND")
    return Principal("demo-tenant","demo-owner","browser-"+workspace_id)

def safe_json_parse(raw:bytes):
    if len(raw)>4096:raise BrokerError("REQUEST_TOO_LARGE")
    def reject_duplicates(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise BrokerError("DUPLICATE_JSON_KEY")
            result[k]=v
        return result
    try:
        obj=json.loads(raw.decode("utf-8"),object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError,UnicodeError):
        raise BrokerError("INVALID_JSON") from None
    if not isinstance(obj,dict):raise BrokerError("INVALID_JSON_OBJECT")
    return obj

class DemoServer(HTTPServer):
    def __init__(self,address,handler=None):
        self.broker,self.adapter=demo_broker()
        super().__init__(address,handler or Handler)

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*_args):
        pass
    def _send(self,status:int,data:bytes,content_type:str):
        self.send_response(status)
        self.send_header("content-type",content_type)
        self.send_header("content-length",str(len(data)))
        self.send_header("cache-control","no-store")
        self.send_header("referrer-policy","no-referrer")
        self.send_header("x-content-type-options","nosniff")
        self.send_header("x-frame-options","DENY")
        self.end_headers()
        self.wfile.write(data)

    def _json(self,status,data):
        self._send(status,json.dumps(data,ensure_ascii=False,separators=(",",":")).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _static(self,kind):
        if kind=="html":
            source=(STATIC/"workspace.html").read_text("utf-8")
            source=source.replace("connect-src 'none'","connect-src 'self'")
            needle='<script type="module" src="./workspace.js"></script>'
            if needle not in source:raise BrokerError("UNEXPECTED_DEMO_TEMPLATE")
            source=source.replace(needle,needle+'\n  <script type="module" src="./demo_connected.js"></script>')
            body=source.encode("utf-8");mime="text/html; charset=utf-8"
        elif kind=="js":
            body=JS.read_bytes();mime="text/javascript; charset=utf-8"
        elif kind=="base_js":
            body=(STATIC/"workspace.js").read_bytes();mime="text/javascript; charset=utf-8"
        elif kind=="css":
            body=(STATIC/"workspace.css").read_bytes();mime="text/css; charset=utf-8"
        else:raise BrokerError("STATIC_RESOURCE_UNKNOWN")
        self._send(200,body,mime)

    def do_GET(self):
        path=urlsplit(self.path)
        try:
            if path.path in ("/","/demo","/demo/"):
                return self._static("html")
            if path.path=="/workspace.js":
                return self._static("base_js")
            if path.path=="/workspace.css":
                return self._static("css")
            if path.path=="/demo_connected.js":
                return self._static("js")
            if path.path=="/_demo/api/poll":
                query=parse_qs(path.query,strict_parsing=True)
                if set(query)!={"workspace_id","request_id"} or any(len(v)!=1 for v in query.values()):
                    raise BrokerError("INVALID_POLL_QUERY")
                ws,request_id=query["workspace_id"][0],query["request_id"][0]
                result=asyncio.run(self.server.broker.poll(principal(ws),request_id))
                return self._json(200,result)
            if path.path=="/_demo/api/status":
                query=parse_qs(path.query,strict_parsing=True)
                if set(query)!={"workspace_id"} or len(query["workspace_id"])!=1:
                    raise BrokerError("INVALID_STATUS_QUERY")
                result=asyncio.run(self.server.broker.summary(principal(query["workspace_id"][0])))
                return self._json(200,result)
            return self._json(404,{"error":"not_found"})
        except (BrokerError,ValueError):
            return self._json(400,{"error":"INVALID_REQUEST"})
        except Exception:
            return self._json(503,{"error":"DEMO_UNAVAILABLE"})

    def do_POST(self):
        path=urlsplit(self.path)
        if path.path not in ("/_demo/api/open","/_demo/api/close") or path.query:
            return self._json(404,{"error":"not_found"})
        expected="http://"+self.headers.get("Host","")
        if self.headers.get("Origin")!=expected:
            return self._json(403,{"error":"ORIGIN_REQUIRED"})
        if self.headers.get("content-type","").split(";")[0]!="application/json":
            return self._json(415,{"error":"JSON_REQUIRED"})
        try:
            length=int(self.headers.get("content-length","0"))
        except ValueError:
            return self._json(400,{"error":"INVALID_BODY"})
        if not 1<=length<=4096:return self._json(413,{"error":"BODY_SIZE_LIMIT"})
        try:
            data=safe_json_parse(self.rfile.read(length))
            if path.path=="/_demo/api/open":
                if set(data)!={"workspace_id","url","request_id","tab_id"}:
                    raise BrokerError("INVALID_OPEN_FIELDS")
                if type(data["tab_id"]) is not int or data["tab_id"]<1:
                    raise BrokerError("INVALID_TAB_ID")
                workspace=data["workspace_id"]
                result=asyncio.run(self.server.broker.open(
                    principal(workspace),workspace,data["url"],data["request_id"]))
            else:
                if set(data)!={"workspace_id"}:raise BrokerError("INVALID_CLOSE_FIELDS")
                result=asyncio.run(self.server.broker.close(principal(data["workspace_id"])))
            return self._json(200,result)
        except BrokerError:
            return self._json(409,{"error":"BROKER_REQUEST_REJECTED"})
        except Exception:
            return self._json(503,{"error":"DEMO_UNAVAILABLE"})

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8060)
    args=parser.parse_args(argv)
    if not 0<=args.port<=65535:raise SystemExit("Invalid demo port")
    server=DemoServer(("127.0.0.1",args.port))
    print("AI_BROWSER_LOCAL_DEMO_LISTENING_127_0_0_1:"+str(server.server_port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=="__main__":
    main()

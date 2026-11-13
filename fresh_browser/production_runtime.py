"""Owner-scoped WordPress REST, durable write receipts and bounded file delivery.

Uses the existing browser cookie session and WordPress's own REST nonce, inside
the same origin. No credentials are exported, copied or added to the database.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit, unquote
from email.utils import parsedate_to_datetime

from fastapi import HTTPException, Request
from fastapi.responses import Response
import server

WP_PROFILE = "wordpress-klinika"
WP_ORIGIN = "https://weterynarz.radom.pl"
FIELDS = {"title", "content", "excerpt", "status", "featured_media", "alt_text", "caption", "description", "menu_order", "template", "styles", "settings"}
RESOURCES = r"(?:pages|posts|media|templates|template-parts|global-styles)"
WP_COOLDOWN_UNTIL = 0.0
CSS_PATH = r"theme-css/[a-zA-Z0-9_-]+/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_.-]+\.css"
CSS_EDITOR_JS = r"""async ({path, method, body}) => {
  if(location.origin!=='https://weterynarz.radom.pl'||!location.pathname.startsWith('/wp-admin/'))throw new Error('WP origin');
  const parts=path.split('?')[0].split('/'),theme=parts[1],file=parts.slice(2).join('/');
  const r=await fetch('/wp-admin/theme-editor.php?'+new URLSearchParams({theme,file}),{credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(30000)});
  const html=await r.text();if(!r.ok||html.length>2000000)throw new Error('Editor unavailable');
  const doc=new DOMParser().parseFromString(html,'text/html'),area=doc.querySelector('textarea[name="newcontent"]'),form=area?.closest('form');
  if(!form||!area||form.querySelector('[name="theme"]')?.value!==theme||form.querySelector('[name="file"]')?.value!==file)return {status:403,data:{code:'theme_editor_not_authorized'}};
  if(method==='POST'){
    const nonce=form.querySelector('[name="nonce"],[name="_wpnonce"]')?.value;
    if(!nonce)return {status:403,data:{code:'theme_nonce_missing'}};
    const sent=await fetch('/wp-admin/admin-ajax.php',{method:'POST',credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({action:'edit-theme-plugin-file',theme,file,nonce,newcontent:body.content}),signal:AbortSignal.timeout(30000)});
    const receipt=await sent.json();if(!sent.ok||!receipt.success)return {status:sent.ok?409:sent.status,data:{code:'theme_write_not_confirmed'}};
  }
  return {status:200,data:{id:theme+':'+file,type:'theme-css',content:{raw:area.value},link:location.origin+'/wp-content/themes/'+theme+'/'+file}};
}"""
WP_FETCH = r"""async ({path, method, body, upload}) => {
  if (location.origin !== 'https://weterynarz.radom.pl' || !location.pathname.startsWith('/wp-admin/')) throw new Error('WP origin');
  const nonceResponse = await fetch('/wp-admin/admin-ajax.php?action=rest-nonce', {credentials:'same-origin', redirect:'error'});
  const nonce = (await nonceResponse.text()).trim();
  if (!nonceResponse.ok || !/^[a-zA-Z0-9]{10}$/.test(nonce)) return {status:401, data:{code:'owner_session_required'}};
  const headers = {'X-WP-Nonce':nonce};
  let data;
  if(upload){
    data=new FormData(); const bytes=Uint8Array.from(atob(upload.base64), c=>c.charCodeAt(0));
    data.append('file',new Blob([bytes],{type:upload.mime}),upload.filename);
    if(upload.title)data.append('title',upload.title);
  } else if(body !== undefined){headers['Content-Type']='application/json';data=JSON.stringify(body);}
  const r=await fetch('/wp-json/wp/v2/'+path,{method,headers,body:data,credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(30000)});
  const text=await r.text(); if(text.length>2000000)throw new Error('WP response bound');
  let value;try{value=JSON.parse(text)}catch{return {status:502,data:{code:'invalid_wordpress_response'}};}
  return {status:r.status,data:value,retry_after:r.headers.get('Retry-After'),total:r.headers.get('X-WP-Total')};
}"""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_spec(raw):
    try:
        spec = json.loads(raw)
        if not isinstance(spec, dict): raise ValueError()
        path, method = spec.get("path", ""), spec.get("method", "GET")
        if method not in {"GET", "POST"} or not isinstance(path, str) or len(path) > 1500: raise ValueError()
        parts = urlsplit(path)
        if parts.scheme or parts.netloc or parts.fragment or "%" in parts.path or ".." in path or "\\" in path: raise ValueError()
        if not re.fullmatch(RESOURCES + r"(?:/(?:[1-9][0-9]*|[a-zA-Z0-9_-]+//[a-zA-Z0-9_-]+))?(?:/revisions)?|users/me|themes|" + CSS_PATH, parts.path): raise ValueError()
        query = parse_qs(parts.query)
        if set(query) - {"context", "per_page", "page", "search", "status", "slug", "parent", "_fields"}: raise ValueError()
        if any(len(v) != 1 for v in query.values()): raise ValueError()
        if int(query.get("per_page", ["10"])[0]) not in range(1, 21): raise ValueError()
        if method == "POST":
            if parts.query or parts.path in {"users/me", "themes"} or parts.path.endswith("/revisions"): raise ValueError()
            if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", spec.get("operation_id", "")): raise ValueError()
            body = spec.get("body", {})
            if not isinstance(body, dict) or set(body) - FIELDS: raise ValueError()
            if len(json.dumps(body).encode()) > 20000: raise ValueError()
            if parts.path.startswith("theme-css/") and (set(body)!={"content"} or not isinstance(body["content"],str) or re.search(r"<\?|@import|expression\s*\(|javascript:",body["content"],re.I)): raise ValueError()
            if "/" not in parts.path and parts.path != "media" and body.get("status") != "draft": raise ValueError()
            if "/" in parts.path and not re.fullmatch(r"[a-f0-9]{64}", spec.get("expected_sha256", "")): raise ValueError()
            if "upload" in spec:
                upload = spec["upload"]
                if parts.path != "media" or not isinstance(upload, dict): raise ValueError()
                if upload.get("mime") not in {"image/jpeg", "image/png", "image/webp", "application/pdf", "text/plain"}: raise ValueError()
                if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}\.(?:jpg|jpeg|png|webp|pdf|txt)", upload.get("filename", "")): raise ValueError()
                if len(base64.b64decode(upload["base64"], validate=True)) > 8_000_000: raise ValueError()
        elif "body" in spec or "upload" in spec: raise ValueError()
        return spec
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "Niedozwolone lub zbyt obszerne żądanie WordPress REST.") from None


def editable(record):
    if not isinstance(record, dict): return record
    return {k: record[k] for k in sorted(FIELDS | {"id", "modified_gmt", "type", "link", "slug"}) if k in record}


async def backup_document(operation, label, value):
    raw = json.dumps(value, ensure_ascii=False).encode()
    refs = []
    for offset in range(0, len(raw), 24000):
        block = base64.b64encode(raw[offset:offset+24000]).decode()
        ident = "wp-b-" + hashlib.sha256((operation + label + str(offset)).encode()).hexdigest()[:32]
        doc = {"encoding": "base64-json-chunk", "sha256": hashlib.sha256(raw).hexdigest(), "offset": offset, "data": block}
        try: await asyncio.to_thread(server.db_checkpoint, ident, doc)
        except HTTPException as e:
            if e.status_code != 409: raise
            old = await asyncio.to_thread(server.db_checkpoint, ident)
            if old["checkpoint"] != doc: raise HTTPException(409, "Konflikt kopii zapasowej.") from None
        refs.append(ident)
    return {"chunks": refs, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


async def rest(page, path, method="GET", body=None, upload=None):
    global WP_COOLDOWN_UNTIL
    if time.monotonic()<WP_COOLDOWN_UNTIL:
        raise HTTPException(429, {"code":"wordpress_cooldown", "retry_after_seconds":int(WP_COOLDOWN_UNTIL-time.monotonic())+1})
    payload = {"path": path, "method": method}
    if body is not None: payload["body"] = body
    if upload is not None: payload["upload"] = upload
    r = await page.evaluate(CSS_EDITOR_JS if path.startswith("theme-css/") else WP_FETCH, payload)
    if r["status"] >= 400:
        if r["status"]==429:
            raw=r.get("retry_after") or "30"
            try: seconds=int(raw) if str(raw).isdigit() else max(0,parsedate_to_datetime(raw).timestamp()-time.time())
            except (ValueError, TypeError, OverflowError): seconds=30
            WP_COOLDOWN_UNTIL=time.monotonic()+max(1,seconds)
        code = r.get("data", {}).get("code", "wordpress_error")
        code = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", code) else "wordpress_error"
        # No automatic retry, including nonce expiration and WordPress limits.
        raise HTTPException(r["status"], {"code": code, "upstream": "wordpress", "retry_after": r.get("retry_after")})
    return r


async def wordpress_action(args, automated=False, owner_context=None):
    w = server.workspace
    spec = validate_spec(args.get("text", ""))
    if args.get("name") != WP_PROFILE: raise HTTPException(403, "Wymagany istniejący profil WordPress kliniki.")
    async with w.lock:
        if w.context is None or w.profile != WP_PROFILE or w.human:
            raise HTTPException(409, "Otwórz profil WordPress i sprawdź przekazanie sterowania.")
        if owner_context is not None and owner_context is not w.context: raise HTTPException(409, "Sesja wygasła.")
        await w.assert_lease()
        page = w.page()
        if not page.url.startswith(WP_ORIGIN + "/wp-admin/"):
            raise HTTPException(409, "Otwórz kokpit WordPress przed użyciem REST.")
        me = (await rest(page, "users/me?context=edit&_fields=id,name,slug"))["data"]
        if not isinstance(me, dict) or me.get("slug") != "edycjanapieraj":
            raise HTTPException(403, "Nie potwierdzono oczekiwanego konta właściciela.")
        w.last_activity = time.monotonic()
        method, path = spec.get("method", "GET"), spec["path"]
        if method == "GET":
            r = await rest(page, path)
            return {"identity": me, "data": r["data"], "sha256": fingerprint(editable(r["data"])), "total": r.get("total")}
        request_hash = fingerprint(spec)
        task_id = "wp-op-" + hashlib.sha256(spec["operation_id"].encode()).hexdigest()[:32]
        try:
            prior = await asyncio.to_thread(server.db_checkpoint, task_id)
        except HTTPException as e:
            if e.status_code != 404: raise
            prior = None
        if prior:
            state = prior["checkpoint"]
            if state.get("request_hash") != request_hash: raise HTTPException(409, "Ten identyfikator działania ma inną treść.")
            if state.get("phase") == "verified": return {**state["receipt"], "already_confirmed": True}
            raise HTTPException(409, {"code": "write_requires_readback", "task_id": task_id, "phase": state.get("phase")})
        before = editable((await rest(page, path + "?context=edit"))["data"]) if "/" in path else None
        if before is not None and fingerprint(before) != spec["expected_sha256"]:
            raise HTTPException(409, "Treść zmieniono od ostatniego odczytu. Nie wysłano zapisu.")
        before_ref = await backup_document(spec["operation_id"], "before", before)
        desired_ref = await backup_document(spec["operation_id"], "desired", spec.get("body", {}))
        state = {"phase": "prepared", "request_hash": request_hash, "path": path, "before_backup": before_ref, "desired_backup": desired_ref, "account": me["slug"]}
        record = await asyncio.to_thread(server.db_checkpoint, task_id, state)
        # Receipt is durable BEFORE the external write. Even a crash between
        # this transition and network dispatch must never cause a blind replay.
        state["phase"] = "submitted"
        record = await asyncio.to_thread(server.db_checkpoint, task_id, state, record["revision"])
        r = await rest(page, path, "POST", spec.get("body", {}), spec.get("upload"))
        target = path if "/" in path else path + "/" + str(r["data"]["id"])
        state.update(phase="acknowledged", target=target)
        record = await asyncio.to_thread(server.db_checkpoint, task_id, state, record["revision"])
        after = editable((await rest(page, target + "?context=edit"))["data"])
        for key, expected in spec.get("body", {}).items():
            actual = after.get(key)
            if isinstance(actual, dict) and "raw" in actual: actual = actual["raw"]
            if actual != expected: raise HTTPException(409, {"code": "readback_mismatch", "task_id": task_id, "field": key})
        after_ref = await backup_document(spec["operation_id"], "after", after)
        receipt = {"ok": True, "verified": True, "target": target, "sha256": fingerprint(after), "operation_id": spec["operation_id"], "task_id": task_id}
        state.update(phase="verified", receipt=receipt, after_backup=after_ref)
        await asyncio.to_thread(server.db_checkpoint, task_id, state, record["revision"])
        await w._save()
        return {**receipt, "data": after}


_previous_action = server.workspace.action
FILES = {}


def wordpress_cookie_metadata(state):
    """Only expiry metadata, never cookie values, hashes, names or tokens."""
    now = time.time()
    result=[]
    for c in state.get("cookies",[]):
        if str(c.get("domain","")).lstrip(".")!="weterynarz.radom.pl": continue
        name=c.get("name","")
        if not name.startswith(("wordpress_logged_in_","wordpress_sec_")): continue
        fields=unquote(str(c.get("value",""))).split("|")
        expiry=int(fields[1]) if len(fields)==4 and fields[1].isdigit() else None
        result.append({"kind":"logged_in" if name.startswith("wordpress_logged_in_") else "secure_admin",
                       "browser_expires":c.get("expires"), "signed_expires":expiry,
                       "signed_expired":expiry is not None and expiry<now})
    return result


def wordpress_saved_metadata():
    with server.database() as conn:
        rows=conn.execute("SELECT revision,sealed_state FROM fresh_browser.profiles WHERE name=%s UNION ALL SELECT revision,sealed_state FROM (SELECT revision,sealed_state FROM fresh_browser.profile_versions WHERE name=%s ORDER BY revision DESC LIMIT 3) AS versions ORDER BY revision DESC",(WP_PROFILE,WP_PROFILE)).fetchall()
    return [{"revision":r[0],"wordpress_auth_expiry":wordpress_cookie_metadata(json.loads(server.unseal(bytes(r[1]))))} for r in rows]
DOWNLOAD_JS = r"""async ({index}) => {
  const link=document.querySelectorAll('a,button,input,textarea,select')[index];
  if(!link||link.tagName!=='A')throw new Error('Select a file link');
  const url=new URL(link.href,location.href);
  if(url.protocol!=='https:'||url.origin!==location.origin)throw new Error('Same-origin HTTPS files only');
  const r=await fetch(url.href,{credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(30000)});
  if(!r.ok)throw new Error('File HTTP '+r.status);
  if(Number(r.headers.get('content-length'))>8000000){await r.body.cancel();throw new Error('File too large');}
  const reader=r.body.getReader(),chunks=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>8000000){await reader.cancel();throw new Error('File too large');}chunks.push(value);}
  let binary='';for(const chunk of chunks)for(let i=0;i<chunk.length;i+=16384)binary+=String.fromCharCode(...chunk.subarray(i,i+16384));
  return {data:btoa(binary),filename:link.download||url.pathname.split('/').pop()||'download.bin',mime:r.headers.get('content-type')||'application/octet-stream'};
}"""


def current_files():
    w = server.workspace
    for ident, entry in list(FILES.items()):
        if entry["context"] is not w.context or entry["until"] <= time.monotonic(): FILES.pop(ident)
    return FILES


@server.app.get("/api/downloads")
@server.app.get("/owner/api/downloads")
async def downloads(request: Request, name: str):
    check_file_access(request, name)
    return {"downloads": [{"id": k, "filename": v["filename"], "bytes": len(v["data"])} for k,v in current_files().items()]}


def check_file_access(request, name):
    if request.url.path.startswith("/owner/"):
        grant=server.require_owner(request)
        if grant["name"] != name or grant["context"] is not server.workspace.context: raise HTTPException(409, "Sesja wygasła.")
    else: server.require(request)
    if server.workspace.context is None or server.workspace.profile != name: raise HTTPException(409, "Profil nie jest otwarty.")


@server.app.get("/api/downloads/{ident}")
@server.app.get("/owner/api/downloads/{ident}")
async def download_file(request: Request, ident: str, name: str):
    check_file_access(request, name)
    item=current_files().get(ident)
    if not item: raise HTTPException(404, "Plik wygasł. Pobierz ponownie z witryny.")
    return Response(item["data"], media_type="application/octet-stream", headers={"Content-Disposition": 'attachment; filename="'+item["filename"]+'"', "Content-Security-Policy":"sandbox; default-src 'none'"})

async def production_action(args, automated=False, owner_context=None):
    if args.get("action")=="wordpress_session_status":
        if args.get("name")!=WP_PROFILE: raise HTTPException(403,"Wymagany profil WordPress.")
        return {"observed_at":int(time.time()),"saved_versions":await asyncio.to_thread(wordpress_saved_metadata)}
    if args.get("action") == "wordpress_rest":
        return await wordpress_action(args, automated, owner_context)
    if args.get("action") in {"close_tab", "file_fields", "download"}:
        w = server.workspace
        async with w.lock:
            if w.context is None or w.profile != args.get("name") or (automated and w.human): raise HTTPException(409, "Profil niedostępny.")
            if owner_context is not None and owner_context is not w.context: raise HTTPException(409, "Sesja wygasła.")
            await w.assert_lease()
            page = w.page()
            if args.get("page_id") and args["page_id"] != w.tab_id(page): raise HTTPException(409, "Karta uległa zmianie.")
            if args["action"] == "file_fields":
                fields = await page.locator("a,button,input,textarea,select").evaluate_all("els=>els.slice(0,150).flatMap((e,index)=>e.type==='file'?[{index,label:e.getAttribute('aria-label')||e.name||'Plik'}]:[])")
                links = await page.locator("a,button,input,textarea,select").evaluate_all("els=>els.slice(0,150).flatMap((e,index)=>e.tagName==='A'&&(/\\.(pdf|png|jpg|jpeg|webp|zip|txt|csv|xlsx|docx)(?:[?#]|$)/i.test(e.href)||e.download)?[{index,label:(e.innerText||e.download||'Plik').slice(0,100)}]:[])")
                return {"fields": fields, "links": links, "page_id": w.tab_id(page)}
            if args["action"] == "download":
                index=args.get("index",-1)
                if type(index) is not int or not 0 <= index < 150: raise HTTPException(400,"Wybierz odsyłacz pliku.")
                if len(current_files()) >= 4: raise HTTPException(409,"Zachowaj pobrane pliki i zamknij profil przed kolejnymi.")
                result=await page.evaluate(DOWNLOAD_JS,{"index":index})
                raw=base64.b64decode(result["data"],validate=True)
                if len(raw)>8_000_000: raise HTTPException(413,"Maksymalny plik: 8 MB.")
                ident=secrets.token_hex(16)
                filename=re.sub(r"[^a-zA-Z0-9._-]","_",result["filename"])[:100] or "download.bin"
                FILES[ident]={"context":w.context,"data":raw,"filename":filename,"until":time.monotonic()+900}
                return {"ok":True,"download_id":ident,"filename":filename,"bytes":len(raw),"expires_in":900}
            await page.close(run_before_unload=False)
            if not w.context.pages: await w.context.new_page()
            w.active_page = w.context.pages[-1]
            await w._save()
            return {"ok": True, "tabs": (await w.tab_state())["tabs"]}
    return await _previous_action(args, automated=automated, owner_context=owner_context)

server.workspace.action = production_action

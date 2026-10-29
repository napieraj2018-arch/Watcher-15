"""Private owner task checkpoints on the existing encrypted Floot vault.

A new claim never adopts a live browser capability. Unknown writes remain
blocked until independent readback. This is the existing single-owner beta,
not tenant authorization or an unattended background agent.
"""
from __future__ import annotations
import asyncio, base64, contextvars, copy, hashlib, hmac, json, math, os, re, secrets, time, uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp.server.mcpserver.exceptions import ToolError

class TaskError(ToolError):
    """Expected, fixed-code task refusal safe to expose through MCP 2.3."""
    pass
PROFILE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$')
OP = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')
ACTIONS = {'browser_navigate','browser_snapshot','browser_status','browser_auth_status',
 'browser_click','browser_fill','browser_press','browser_scroll','browser_tabs',
 'browser_new_tab','browser_switch_tab','browser_close_tab','browser_back',
 'browser_forward','browser_reload','browser_set_viewport','browser_page_metadata'}
READS = {'browser_snapshot','browser_status','browser_auth_status','browser_tabs','browser_page_metadata'}
VAULT_RATE_LIMIT_DEFAULT_SECONDS = 900
VAULT_RATE_LIMIT_MAX_SECONDS = 86400


def vault_retry_after_seconds(value, *, now=None):
    """Bound a vault 429 cooldown without reading or logging its response body."""
    if not isinstance(value, str) or not 1 <= len(value) <= 96:
        return VAULT_RATE_LIMIT_DEFAULT_SECONDS
    raw = value.strip()
    seconds = None
    if re.fullmatch(r'[0-9]{1,10}', raw):
        seconds = int(raw)
    else:
        try:
            deadline = parsedate_to_datetime(raw)
            if deadline.tzinfo is not None:
                clock = now if now is not None else datetime.now(timezone.utc)
                if clock.tzinfo is not None:
                    seconds = math.ceil((deadline - clock).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    if seconds is None or seconds <= 0:
        return VAULT_RATE_LIMIT_DEFAULT_SECONDS
    return max(VAULT_RATE_LIMIT_DEFAULT_SECONDS,
               min(VAULT_RATE_LIMIT_MAX_SECONDS, seconds))

def canonical(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
def unpack(v):
    if isinstance(v,str): return json.loads(v)
    return v

def validate_checkpoint(data):
    if not isinstance(data,dict) or set(data)-{'last_confirmed_step','remaining_steps','status','required_permissions','handoff_after_saved_close'}:
        raise TaskError('TASK_CHECKPOINT_FIELDS_INVALID')
    if 'handoff_after_saved_close' in data and type(data['handoff_after_saved_close']) is not bool:
        raise TaskError('TASK_HANDOFF_FLAG_INVALID')
    if len(canonical(data))>20000: raise TaskError('TASK_CHECKPOINT_TOO_LARGE')
    if 'remaining_steps' in data and (not isinstance(data['remaining_steps'],list) or len(data['remaining_steps'])>100 or any(not isinstance(x,str) or len(x)>1000 for x in data['remaining_steps'])):
        raise TaskError('TASK_STEPS_INVALID')
    return data

class Vault:
    def __init__(self):
        raw=os.environ.get('AI_BROWSER_MASTER_KEY','').encode()
        self.key=hmac.new(raw,b'task-checkpoint-v1',hashlib.sha256).digest()
        self.owner=hashlib.sha256(os.environ.get('AI_BROWSER_MCP_TOKEN','').encode()).hexdigest()
        self.token=os.environ.get('AI_BROWSER_PROFILE_STORE_TOKEN','')
        # One vault writer lane per controller. A 429 blocks all calls for a
        # bounded period, not just this task, preventing a Free-tier retry storm.
        self._http_lock=asyncio.Lock()
        self._rate_limit_until=0.0
        if not raw or not self.token: raise TaskError('TASK_VAULT_NOT_CONFIGURED')
        url=os.environ.get('AI_BROWSER_PROFILE_STORE_URL','')
        if url!='https://ai-browser-vault.floot.app/_api/profile-vault':
            raise TaskError('TASK_VAULT_ORIGIN_NOT_VERIFIED')
        self.url=url.rsplit('/',1)[0]+'/task-vault'
    def seal(self,tid,data):
        nonce=secrets.token_bytes(12)
        raw=canonical(data).encode()
        if len(raw)>180000: raise TaskError('TASK_CHECKPOINT_TOO_LARGE')
        return base64.urlsafe_b64encode(nonce+AESGCM(self.key).encrypt(nonce,raw,(self.owner+tid).encode())).decode()
    def open(self,tid,sealed):
        try:
            raw=base64.urlsafe_b64decode(sealed)
            return json.loads(AESGCM(self.key).decrypt(raw[:12],raw[12:],(self.owner+tid).encode()))
        except Exception: raise TaskError('TASK_CHECKPOINT_DECRYPT_FAILED') from None
    async def request(self,**body):
        async with self._http_lock:
            if time.monotonic()<self._rate_limit_until:
                raise TaskError('TASK_VAULT_RATE_LIMITED')
            try:
                async with httpx.AsyncClient(timeout=20,follow_redirects=False) as c:
                    r=await c.post(self.url,headers={'authorization':'Bearer '+self.token},json=body)
                if r.status_code==429:
                    self._rate_limit_until=time.monotonic()+vault_retry_after_seconds(
                        r.headers.get('retry-after'))
                    raise TaskError('TASK_VAULT_RATE_LIMITED')
                if r.status_code==409: raise TaskError('TASK_CONFLICT_OR_RECOVERY_REQUIRED')
                if r.status_code!=200: raise TaskError('TASK_VAULT_HTTP_'+str(r.status_code))
                return r.json()
            except (httpx.HTTPError,ValueError):
                raise TaskError('TASK_VAULT_UNCONFIRMED') from None

class TaskService:
    def __init__(self,vault,registry,guard):
        self.vault,self.registry,self.guard=vault,registry,guard
        self.starting_task=contextvars.ContextVar('aib_durable_start',default=None)
        self.start_checkpoint=contextvars.ContextVar('aib_durable_start_checkpoint',default=None)
        self.admission_checkpoint=hasattr(guard,'before_provider_start')
        if self.admission_checkpoint:
            previous=guard.before_provider_start
            async def admitted(profile):
                if previous is not None: await previous(profile)
                pending=self.start_checkpoint.get()
                if pending is not None and pending[0]==profile: await pending[1]()
            guard.before_provider_start=admitted
        self.stopping=set()
        self.internal_sessions={}
        self.finalizers=set()
        self.bindings={}  # Only this process and task's fresh claim know a live capability.
        self.locks={}
    def lock(self,tid): return self.locks.setdefault(tid,asyncio.Lock())
    async def load(self,tid):
        try: uuid.UUID(tid)
        except (ValueError,TypeError): raise TaskError('TASK_ID_INVALID') from None
        row=(await self.vault.request(action='get',task_id=tid))['task']
        data=self.vault.open(tid,row['encryptedState'])
        if data.get('task_id')!=tid or data.get('owner')!=self.vault.owner: raise TaskError('TASK_BINDING_INVALID')
        return row,data
    async def save(self,row,data,claim):
        r=await self.vault.request(action='save',task_id=data['task_id'],claim=claim,
         expected_revision=row['revision'],state=self.vault.seal(data['task_id'],data),
         resumable=data['session_state'] in {'none','saved_closed'},queued=data.get('queued',False))
        row['revision']=r['revision']
    async def invoke(self,name,args):
        if name not in self.registry: raise TaskError('TASK_TOOL_NOT_AVAILABLE')
        return unpack(await self.registry[name].fn(**args))
    def public(self,row,data):
        result=copy.deepcopy(data)
        result.pop('claim_hash',None)
        result['revision']=row['revision']
        result['durable_checkpoint_supported']=True
        result['live_browser_adoption_supported']=False
        return result
    def authorize(self,data,claim):
        if not isinstance(claim,str) or not hmac.compare_digest(data.get('claim_hash',''),hashlib.sha256(claim.encode()).hexdigest()):
            raise TaskError('TASK_NOT_OWNED')
    async def release_verified_handoff(self,row,data,claim):
        """Opt-in only: release a claim after a durable saved_closed receipt.

        If the vault refuses/limits the release, the previously committed
        saved-close state remains untouched. Its claim expires normally;
        never falsely claim that another chat can resume immediately.
        """
        if data.get('handoff_after_saved_close') is not True:
            return False
        if data.get('session_state')!='saved_closed':
            raise TaskError('TASK_SAVE_CLOSE_REQUIRED')
        try:
            await self.vault.request(action='release',task_id=data['task_id'],
                                     claim=claim,expected_revision=row['revision'])
        except TaskError:
            return False
        return True
    async def create(self,profile,title,checkpoint):
        if not PROFILE.fullmatch(profile or '') or not isinstance(title,str) or not 1<=len(title)<=200:
            raise TaskError('TASK_INPUT_INVALID')
        validate_checkpoint(checkpoint)
        tid=str(uuid.uuid4()); claim=secrets.token_hex(32)
        data={'task_id':tid,'owner':self.vault.owner,'profile':profile,'title':title,
          'last_confirmed_step':'','remaining_steps':[],'status':'ready','operations':{},
          'session_state':'none','queued':False,'handoff_after_saved_close':False,
          'created_at':int(time.time()),**checkpoint,
          'claim_hash':hashlib.sha256(claim.encode()).hexdigest()}
        r=await self.vault.request(action='create',task_id=tid,claim=claim,state=self.vault.seal(tid,data))
        return {**self.public(r,data),'task_claim':claim}
    async def run(self,action,task_id='',task_claim='',profile='',title='',data_json='{}',operation_id='',browser_tool='',expected_text=''):
        try: args=json.loads(data_json)
        except (ValueError,TypeError): raise TaskError('TASK_JSON_INVALID') from None
        if len(data_json)>20000 or not isinstance(args,dict): raise TaskError('TASK_JSON_INVALID')
        if action=='create': return await self.create(profile,title,args)
        if action=='list':
            rows=(await self.vault.request(action='list'))['tasks']
            return {'tasks':[self.public(r,self.vault.open(r['taskId'],r['encryptedState'])) for r in rows]}
        async with self.lock(task_id):
            if action=='resume':
                row=(await self.vault.request(action='claim',task_id=task_id,claim=(new:=secrets.token_hex(32))))['task']
                data=self.vault.open(task_id,row['encryptedState'])
                if data['session_state'] not in {'none','saved_closed'}: raise TaskError('TASK_SESSION_RECONCILIATION_REQUIRED')
                data['claim_hash']=hashlib.sha256(new.encode()).hexdigest()
                await self.save(row,data,new)
                return {**self.public(row,data),'task_claim':new}
            row,data=await self.load(task_id)
            if action=='get': return self.public(row,data)
            self.authorize(data,task_claim)
            if action=='checkpoint':
                validate_checkpoint(args); data.update(args); await self.save(row,data,task_claim)
            elif action=='start':
                if data['session_state'] not in {'none','saved_closed'}: raise TaskError('TASK_SESSION_NOT_CLOSED')
                if set(args)-{'mode','headless'} or type(args.get('mode','write')) is not str or args.get('mode','write') not in {'read_only','write'} or type(args.get('headless',False)) is not bool:
                    raise TaskError('TASK_START_ARGUMENTS_INVALID')
                # A durable ticket survives process changes; no browser starts while its caller is absent.
                inventory=self.guard.safe_sessions()
                if inventory:
                    if any(x.get('state') in {'provider_reconciliation_required','recovery_required','missing_session_quarantined','unmanaged_quarantined'} for x in inventory):
                        raise TaskError('TASK_PROVIDER_RECONCILIATION_REQUIRED')
                busy=profile_busy= False
                if len(self.guard.leases)>=self.guard.capacity: busy=True
                if data['profile'] in self.guard.by_profile: profile_busy=True
                if busy or profile_busy:
                    data['queued']=True; await self.save(row,data,task_claim)
                    return {**self.public(row,data),'queue_reason':'profile_busy' if profile_busy else 'capacity','started':False}
                # Checkpoint BEFORE a possibly billable provider create.
                async def checkpoint_start():
                    data['queued']=False; data['session_state']='starting'; await self.save(row,data,task_claim)
                # An admission race/refusal must not strand a never-started task
                # in global recovery. The real guard calls this under its lock,
                # after all refusals and BEFORE any billable provider creation.
                if not self.admission_checkpoint: await checkpoint_start()
                try:
                    token=self.starting_task.set(task_id)
                    checkpoint_token=self.start_checkpoint.set((data['profile'],checkpoint_start))
                    try:
                        result=await self.invoke('browser_start',{'profile':data['profile'],'mode':args.get('mode','write'),'headless':args.get('headless',False)})
                    finally:
                        self.start_checkpoint.reset(checkpoint_token)
                        self.starting_task.reset(token)
                    self.bindings[task_id]=(task_claim,result['session_id'])
                    if hasattr(self.guard,'authorize'):
                        self.internal_sessions[task_id]=self.guard.authorize(result['session_id']).internal_session_id
                    data['session_state']='active'; await self.save(row,data,task_claim)
                except BaseException:
                    # Do not restart or clear a provider outcome whose receipt was lost.
                    raise
                return {**self.public(row,data),'browser':result}
            elif action=='stop':
                claim,handle=self.bindings.get(task_id,('',''))
                if not handle or not hmac.compare_digest(claim,task_claim): raise TaskError('TASK_LIVE_SESSION_NOT_OWNED')
                data['session_state']='closing'; await self.save(row,data,task_claim)
                self.stopping.add(task_id)
                try:
                    result=await self.invoke('browser_stop',{'session_id':handle})
                finally:
                    self.stopping.discard(task_id)
                if (result.get('full_profile_saved') is not True
                        or result.get('profile_saved') is not True
                        or result.get('stopped') is not True):
                    raise TaskError('TASK_FULL_SAVE_UNCONFIRMED')
                self.bindings.pop(task_id,None); self.internal_sessions.pop(task_id,None); data['session_state']='saved_closed'
                data['last_saved_at']=int(time.time()); await self.save(row,data,task_claim)
                handoff=await self.release_verified_handoff(row,data,task_claim)
                return {**self.public(row,data),'saved_close':result,
                        'claim_released':handoff,'handoff_requested':data.get('handoff_after_saved_close') is True}
            elif action=='release':
                if data['session_state'] not in {'none','saved_closed'}: raise TaskError('TASK_SAVE_CLOSE_REQUIRED')
                await self.vault.request(action='release',task_id=task_id,claim=task_claim,expected_revision=row['revision'])
                return {'released':True,'task_id':task_id,'checkpoint_persisted':True}
            elif action in {'browser','begin','confirm','verify'}:
                if not OP.fullmatch(operation_id or '') and action!='browser': raise TaskError('TASK_OPERATION_ID_REQUIRED')
                ops=data['operations']; prior=ops.get(operation_id)
                if action=='begin':
                    fingerprint=hashlib.sha256(canonical(args).encode()).hexdigest()
                    if prior:
                        if prior['fingerprint']!=fingerprint: raise TaskError('TASK_OPERATION_ID_REUSED')
                        return {'execute':False,'operation':prior,'verification_required':prior['status']!='confirmed'}
                    if any(x['status']!='confirmed' for x in ops.values()): raise TaskError('TASK_UNCERTAIN_OPERATION_MUST_BE_VERIFIED')
                    if len(ops)>=200: raise TaskError('TASK_OPERATION_LIMIT')
                    ops[operation_id]={'fingerprint':fingerprint,'status':'started','at':int(time.time())}
                    await self.save(row,data,task_claim)
                    return {'execute':True,'operation_id':operation_id,'revision':row['revision']}
                if action=='confirm':
                    # External connector receipt is evidence supplied by the authorized owner agent.
                    if not prior or not isinstance(args.get('receipt'),str) or not 1<=len(args['receipt'])<=2000:
                        raise TaskError('TASK_RECEIPT_REQUIRED')
                    prior.update(status='confirmed',receipt=args['receipt']); await self.save(row,data,task_claim)
                else:
                    claim,handle=self.bindings.get(task_id,('',''))
                    if not handle or not hmac.compare_digest(claim,task_claim): raise TaskError('TASK_LIVE_SESSION_NOT_OWNED')
                    if action=='verify':
                        if not prior or not expected_text or len(expected_text)>1000: raise TaskError('TASK_VERIFICATION_REQUIRED')
                        observed=await self.invoke('browser_snapshot',{'session_id':handle,'max_text_chars':20000})
                        if expected_text not in observed.get('text',''): return {'verified':False,'operation_id':operation_id}
                        prior.update(status='confirmed',receipt='browser_readback:'+hashlib.sha256(expected_text.encode()).hexdigest())
                        await self.save(row,data,task_claim)
                        return {'verified':True,'operation_id':operation_id,'readback':observed}
                    if browser_tool not in ACTIONS or 'session_id' in args: raise TaskError('TASK_BROWSER_ACTION_INVALID')
                    if browser_tool not in READS:
                        if not OP.fullmatch(operation_id or ''): raise TaskError('TASK_OPERATION_ID_REQUIRED')
                        fingerprint=hashlib.sha256(canonical([browser_tool,args]).encode()).hexdigest()
                        if prior:
                            if prior['fingerprint']!=fingerprint: raise TaskError('TASK_OPERATION_ID_REUSED')
                            return {'executed':False,'operation':prior,'verification_required':prior['status']!='confirmed'}
                        if any(x['status']!='confirmed' for x in ops.values()): raise TaskError('TASK_UNCERTAIN_OPERATION_MUST_BE_VERIFIED')
                        if len(ops)>=200: raise TaskError('TASK_OPERATION_LIMIT')
                        ops[operation_id]={'fingerprint':fingerprint,'status':'started','at':int(time.time())}
                        await self.save(row,data,task_claim)
                    result=await self.invoke(browser_tool,{'session_id':handle,**args})
                    if browser_tool not in READS:
                        ops[operation_id]['status']=('unverified' if browser_tool in {'browser_click','browser_fill','browser_press'} else 'confirmed')
                        ops[operation_id]['receipt']='tool_result:'+hashlib.sha256(canonical(result).encode()).hexdigest()
                        await self.save(row,data,task_claim)
                    return {'executed':True,'result':result}
            else: raise TaskError('TASK_ACTION_INVALID')
            return self.public(row,data)

    async def saved_stop(self,internal_sid,result):
        if (not isinstance(result,dict)
                or result.get('full_profile_saved') is not True
                or result.get('profile_saved') is not True
                or result.get('stopped') is not True):
            return
        for tid,(claim,handle) in list(self.bindings.items()):
            if tid in self.stopping: continue
            if self.internal_sessions.get(tid)!=internal_sid: continue
            async with self.lock(tid):
                row,data=await self.load(tid)
                self.authorize(data,claim)
                data['session_state']='saved_closed'; data['last_saved_at']=int(time.time())
                await self.save(row,data,claim)
                self.bindings.pop(tid,None); self.internal_sessions.pop(tid,None)
                await self.release_verified_handoff(row,data,claim)


def install(ns):
    if ns.get('_AIB_DURABLE_TASKS') is not None: return
    guard=ns.get('_AIB_OWNER_PARALLEL_GUARD')
    if guard is None: return
    service=TaskService(Vault(),ns['mcp']._tool_manager._tools,guard)
    async def aib_task(action:Literal['create','list','get','resume','checkpoint','start','browser','begin','confirm','verify','stop','release'],task_id:str='',task_claim:str='',profile:str='',title:str='',data_json:str='{}',operation_id:str='',browser_tool:str='',expected_text:str='')->dict:
        """Owner-authenticated durable task checkpoint and browser operations.

        Actions: create/list/get/resume/checkpoint/start/browser/begin/confirm/verify/stop/release.
        Resume issues a NEW task claim only after safe saved close; it never adopts a live session.
        For browser mutations use one stable operation_id. An uncertain operation must be verified,
        never retried. begin/confirm also journal authorized connector operations; confirm requires
        a real external receipt. No passwords, tokens or private credentials in data_json.
        For create/checkpoint, data_json accepts last_confirmed_step (string),
        remaining_steps (string array), status (string), required_permissions
        (string array), and handoff_after_saved_close (boolean, opt-in).
        Only an exact full-profile-saved stop permits automatic claim release.
        This does not adopt, restart or schedule an active browser.
        For browser, data_json contains the selected browser tool's arguments WITHOUT session_id.
        For start, data_json may contain mode (read_only/write) and headless (boolean).
        begin accepts safe operation metadata; confirm requires a receipt string.
        """
        return await service.run(action,task_id,task_claim,profile,title,data_json,operation_id,browser_tool,expected_text)
    ns['mcp'].tool()(aib_task)
    ns['_AIB_DURABLE_TASKS']=service
    original_start=service.registry['browser_start'].fn
    async def task_start_gate(**args):
        # A process restart cannot silently erase an unfinished task's browser lease.
        rows=(await service.vault.request(action='list'))['tasks']
        for row in rows:
            tid=row['taskId']
            if row.get('resumable') is False and tid not in service.bindings and tid!=service.starting_task.get():
                raise TaskError('TASK_INTERRUPTED_SESSION_RECONCILIATION_REQUIRED')
        return await original_start(**args)
    service.registry['browser_start'].fn=task_start_gate
    previous_stop=guard.manager.stop
    async def durable_saved_stop(sid,*args,**kwargs):
        result=await previous_stop(sid,*args,**kwargs)
        # Never await task.lock under the owner's session.lock (watchdog order).
        # Preserve the non-resumable row until this durable finalizer succeeds.
        if any(service.internal_sessions.get(tid)==sid and tid not in service.stopping for tid in service.bindings):
            job=asyncio.create_task(service.saved_stop(sid,unpack(result)))
            service.finalizers.add(job)
            def consume(done):
                service.finalizers.discard(done)
                if not done.cancelled(): done.exception()
            job.add_done_callback(consume)
        return result
    guard.manager.stop=durable_saved_stop

"""Real PostgreSQL 16 owner/actor/lease reattach and cancellation race test.

All fixture UUIDs, cookies and CSRF tokens here are fictional.
Connects only to the disposable local GitHub Actions PostgreSQL instance.
NO real Steel, users, encrypted states, provider profiles or billing.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from uuid import UUID, uuid4
import psycopg

DB=dict(host="127.0.0.1",port=5432,dbname="postgres",autocommit=True)
A=UUID("11111111-1111-4111-8111-111111111111")
B=UUID("22222222-2222-4222-8222-222222222222")
WA=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PA=UUID("aaaaaaaa-0000-4000-8000-000000000001")
PB=UUID("bbbbbbbb-0000-4000-8000-000000000002")
UA=UUID("aaaaaaaa-eeee-4eee-8eee-000000000001")
UB=UUID("bbbbbbbb-eeee-4eee-8eee-000000000002")
OTHER_A=UUID("aaaaaaaa-eeee-4eee-8eee-000000000003")
TASK_A=UUID("aaaaaaaa-ffff-4fff-8fff-000000000001")
TASK_B=UUID("bbbbbbbb-ffff-4fff-8fff-000000000002")
TASK_CANCEL=UUID("aaaaaaaa-ffff-4fff-8fff-000000000003")
PROFILE_CANCEL=UUID("aaaaaaaa-dddd-4ddd-8ddd-000000000003")

def digest(value):
    return sha256(value.encode("ascii")).hexdigest()

# Pretend these are opaque randomly minted browser auth-cookie tokens.
# Actual production BFF would validate a cookie's digest and a CSRF
# secret derived separately; none of these fixtures are usable credentials.
AUTH_A=digest("synthetic-A-first-session-20261010"*2)
AUTH_A_NEW=digest("synthetic-A-fresh-chat-session-20261010"*2)
AUTH_B=digest("synthetic-B-session-20261010"*2)
AUTH_OTHER=digest("synthetic-A-other-principal-20261010"*2)
CSRF_A=digest("synthetic-csrf-A-20261010"*3)
CSRF_B=digest("synthetic-csrf-B-20261010"*3)
CSRF_OTHER=digest("synthetic-csrf-other-20261010"*3)

def cx(user):
    return psycopg.connect(user=user,**DB)

def bff(sql,params):
    with cx("fixture_recovery_bff") as conn:
        return conn.execute(sql,params).fetchone()

def verifier(slot,lease,gen,alive=True,same=True):
    with cx("fixture_parallel_verify") as conn:
        return conn.execute(
            "SELECT browser_recovery.record_provider_readback(%s,%s,%s,%s,%s)",
            (slot,lease,gen,alive,same)
        ).fetchone()[0]

def worker(tenant,sql,params):
    user="fixture_parallel_a" if tenant==A else "fixture_parallel_b"
    with cx(user) as conn:
        return conn.execute(sql,params).fetchone()[0]

def listed(session,csrf):
    with cx("fixture_recovery_bff") as conn:
        return conn.execute(
            "SELECT * FROM browser_recovery.list_own_tasks(%s,%s)",
            (session,csrf)
        ).fetchall()

# CI test setup only. Never run these resets against production or Floot.
with cx("postgres") as db:
    db.execute("CREATE ROLE fixture_recovery_bff LOGIN IN ROLE browser_bff_auth")
    db.execute(
        "UPDATE browser_parallel.slots SET state='free',"
        "tenant_id=NULL,profile_id=NULL,task_id=NULL,"
        "lease_id=NULL,expires_at=NULL"
    )
    db.execute("DELETE FROM browser_product.browser_tasks")
    db.execute("DELETE FROM browser_auth.sessions")
    db.execute("DELETE FROM browser_auth.memberships")
    db.execute(
        "UPDATE browser_product.login_tenant_bindings SET enabled=true "
        "WHERE db_role IN ('fixture_parallel_a','fixture_parallel_b')"
    )
    db.execute(
        "UPDATE browser_product.profiles SET status='ready' "
        "WHERE (tenant_id,profile_id) IN ((%s,%s),(%s,%s))",
        (A,PA,B,PB)
    )
    db.execute(
        "INSERT INTO browser_product.profiles "
        "(tenant_id,workspace_id,profile_id,display_name,status) "
        "VALUES(%s,%s,%s,'Recovery synthetic new profile','ready')",
        (A,WA,PROFILE_CANCEL)
    )
    for tenant,principal in ((A,UA),(B,UB),(A,OTHER_A)):
        db.execute(
            "INSERT INTO browser_auth.memberships("
            "principal_id,tenant_id,access_role) VALUES(%s,%s,'operator')",
            (principal,tenant)
        )
    for sid,csrf,tenant,principal in (
        (AUTH_A,CSRF_A,A,UA),(AUTH_A_NEW,CSRF_A,A,UA),
        (AUTH_B,CSRF_B,B,UB),(AUTH_OTHER,CSRF_OTHER,A,OTHER_A)):
        db.execute(
            "INSERT INTO browser_auth.sessions("
            "session_digest,csrf_digest,tenant_id,principal_id,expires_at)"
            " VALUES(%s,%s,%s,%s,clock_timestamp()+interval '1 hour')",
            (sid,csrf,tenant,principal)
        )
    for tenant,ws,profile,task in (
        (A,WA,PA,TASK_A),(B,WB,PB,TASK_B),
        (A,WA,PROFILE_CANCEL,TASK_CANCEL)):
        db.execute(
            "INSERT INTO browser_product.browser_tasks("
            "tenant_id,workspace_id,profile_id,task_id) VALUES(%s,%s,%s,%s)",
            (tenant,ws,profile,task)
        )
    assert db.execute(
        "SELECT active_limit,provider_limit FROM browser_parallel.capacity"
    ).fetchone()==(5,10)

# No broad client or worker access to owner's private recovery tables.
with cx("postgres") as db:
    assert not db.execute(
        "SELECT has_table_privilege('fixture_recovery_bff',"
        "'browser_recovery.owned_tasks','SELECT')"
    ).fetchone()[0]
    assert not db.execute(
        "SELECT has_function_privilege('fixture_recovery_bff',"
        "'browser_recovery.record_provider_readback(integer,uuid,bigint,boolean,boolean)',"
        "'EXECUTE')"
    ).fetchone()[0]
    assert not db.execute(
        "SELECT has_function_privilege('fixture_parallel_a',"
        "'browser_recovery.reattach_own_task(text,text,uuid,uuid)',"
        "'EXECUTE')"
    ).fetchone()[0]

# Only an authenticated operator, on an existing queued task, can register.
reg="SELECT browser_recovery.register_own_task(%s,%s,%s)"
assert bff(reg,(AUTH_A,CSRF_A,TASK_A))[0]=="registered"
assert bff(reg,(AUTH_A,CSRF_A,TASK_A))[0]=="registered" # idempotent
assert bff(reg,(AUTH_B,CSRF_B,TASK_A))[0]=="not_available" # foreign tenant
assert bff(reg,(AUTH_OTHER,CSRF_OTHER,TASK_A))[0]=="not_available" # same tenant, different principal
assert bff(reg,(AUTH_A,"0"*64,TASK_A))[0]=="not_authorized"
assert bff(reg,("0"*64,CSRF_A,TASK_A))[0]=="not_authorized"
assert bff(reg,(AUTH_A,CSRF_A,TASK_B))[0]=="not_available"
assert bff(reg,(AUTH_B,CSRF_B,TASK_B))[0]=="registered"
assert bff(reg,(AUTH_A,CSRF_A,TASK_CANCEL))[0]=="registered"

assert {x[0] for x in listed(AUTH_A,CSRF_A)}=={TASK_A,TASK_CANCEL}
assert {x[0] for x in listed(AUTH_B,CSRF_B)}=={TASK_B}
assert listed(AUTH_OTHER,CSRF_OTHER)==[]
assert listed(AUTH_A,"0"*64)==[]

def claim(tenant,task):
    lease=uuid4()
    with cx("fixture_parallel_a" if tenant==A else "fixture_parallel_b") as db:
        result=db.execute(
            "SELECT * FROM browser_parallel.claim(%s,%s,300)",(task,lease)
        ).fetchone()
    assert result[0] is True and result[1] is True,result
    assert result[4]=="new"
    return lease,result[2],result[3]

def bind(session,csrf,task,slot,lease,gen):
    return bff(
        "SELECT browser_recovery.bind_reserved_lease(%s,%s,%s,%s,%s,%s)",
        (session,csrf,task,slot,lease,gen)
    )[0]

LA,SA,GA=claim(A,TASK_A)
LB,SB,GB=claim(B,TASK_B)
assert (SA,SB)==(1,2)

# No Steel session creation unless the BFF has bound its task and lease.
can_create="SELECT browser_recovery.can_create_provider(%s,%s,%s,%s)"
assert worker(A,can_create,(TASK_A,LA,SA,GA)) is False
assert bind(AUTH_B,CSRF_B,TASK_A,SA,LA,GA)=="not_available"
assert bind(AUTH_A,CSRF_A,TASK_A,SA,uuid4(),GA)=="lease_not_confirmed"
assert bind(AUTH_A,CSRF_A,TASK_A,SA,LA,GA)=="bound"
assert bind(AUTH_A_NEW,CSRF_A,TASK_A,SA,LA,GA)=="already_bound"
assert worker(A,can_create,(TASK_A,LA,SA,GA)) is True
assert worker(B,can_create,(TASK_A,LA,SA,GA)) is False
assert bind(AUTH_B,CSRF_B,TASK_B,SB,LB,GB)=="bound"
assert worker(B,can_create,(TASK_B,LB,SB,GB)) is True

activate="SELECT browser_parallel.activate(%s,%s,%s,%s)"
assert worker(A,activate,(TASK_A,LA,SA,GA)) is True
assert worker(B,activate,(TASK_B,LB,SB,GB)) is True
assert worker(A,can_create,(TASK_A,LA,SA,GA)) is False

# MUST NOT reattach just because the slot is running. Provider must be
# rechecked by a separate verifier, never a user-supplied boolean.
resume="SELECT * FROM browser_recovery.reattach_own_task(%s,%s,%s,%s)"
attempt0=uuid4()
assert bff(resume,(AUTH_A_NEW,CSRF_A,TASK_A,attempt0))[0]=="provider_recheck_required"
assert bff(resume,(AUTH_B,CSRF_B,TASK_A,uuid4()))[0]=="not_available"
assert bff(resume,(AUTH_OTHER,CSRF_OTHER,TASK_A,uuid4()))[0]=="not_available"
assert bff(resume,(AUTH_A_NEW,"0"*64,TASK_A,uuid4()))[0]=="not_authorized"
assert verifier(SA,LA,GA,False,False) is True
assert bff(resume,(AUTH_A,CSRF_A,TASK_A,attempt0))[0]=="provider_recheck_required"
assert verifier(SA,LA,GA,True,True) is True
assert verifier(SB,LB,GB,True,True) is True

# Sixteen independent callers with EXACTLY the same idempotency nonce
# must increment epoch ONCE, not mint 16 racing capabilities or start Steel.
barrier=Barrier(16)
nonce=uuid4()
def concurrent_resume(_):
    with cx("fixture_recovery_bff") as db:
        barrier.wait(timeout=20)
        return db.execute(resume,(AUTH_A_NEW,CSRF_A,TASK_A,nonce)).fetchone()
with ThreadPoolExecutor(max_workers=16) as pool:
    results=list(pool.map(concurrent_resume,range(16)))
assert sorted(r[0] for r in results)==(
    ["already_attached"]*15+["reattach_epoch_issued"]
),results
assert {r[1:] for r in results}=={(SA,GA,1)}

authorize_action="SELECT browser_recovery.can_execute_epoch(%s,%s,%s,%s,%s)"
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,1)) is True
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,0)) is False
assert worker(B,authorize_action,(TASK_A,LA,SA,GA,1)) is False
assert worker(A,authorize_action,(TASK_A,uuid4(),SA,GA,1)) is False
assert worker(A,authorize_action,(TASK_A,LA,SA,GA+1,1)) is False
assert bff(resume,(AUTH_A_NEW,CSRF_A,TASK_A,nonce))==(
    "already_attached",SA,GA,1
)

# Resuming same task from another BFF login of the SAME principal rotates
# the attachment epoch, revoking the old per-chat handle.
next_nonce=uuid4()
assert bff(resume,(AUTH_A,CSRF_A,TASK_A,next_nonce))==(
    "reattach_epoch_issued",SA,GA,2
)
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,1)) is False
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,2)) is True
assert bff(resume,(AUTH_B,CSRF_B,TASK_A,uuid4()))[0]=="not_available"

# Real BFF + real tenant-worker database adapters issue an encrypted,
# task/actor/epoch-scoped handoff ticket only after a SECOND provider check.
from tenant_security.bff.gate import Principal
from tenant_security.recovery.postgres import PgRecoveryRepository
from tenant_security.recovery.service import (
    ReattachmentService, RecoveryRejected,
)
from tenant_security.recovery.tickets import TaskResumeTickets

auth_dsn="postgresql://fixture_recovery_bff@127.0.0.1:5432/postgres"
workers={
    A:"postgresql://fixture_parallel_a@127.0.0.1:5432/postgres",
    B:"postgresql://fixture_parallel_b@127.0.0.1:5432/postgres",
}
adapter=PgRecoveryRepository(auth_dsn,workers)
assert {record[0] for record in adapter.list_own(AUTH_A_NEW,CSRF_A)}=={
    TASK_A,TASK_CANCEL}
assert adapter.can_execute(A,TASK_A,SA,GA,2) is True
assert adapter.can_execute(B,TASK_A,SA,GA,2) is False

class FakeProviderVerification:
    def verify_active(self,tenant,principal,task,slot,gen):
        return (tenant,principal,task,slot,gen)==(A,UA,TASK_A,SA,GA)

owner=Principal(A,UA,"operator",CSRF_A)
ticket_key=b"synthetic-local-test-key-notreal"
service=ReattachmentService(adapter,FakeProviderVerification(),
                            TaskResumeTickets(ticket_key))
ready=service.resume(principal=owner,session_digest=AUTH_A_NEW,
    csrf_digest=CSRF_A,task_id=TASK_A,attempt_id=uuid4())
assert ready.attachment_epoch==3
assert ready.ticket.startswith("aibr_")
assert service.authorize_ticket(ready.ticket,principal=owner,
    task_id=TASK_A).attachment_epoch==3
assert adapter.can_execute(A,TASK_A,SA,GA,2) is False
assert adapter.can_execute(A,TASK_A,SA,GA,3) is True
try:
    service.authorize_ticket(ready.ticket,
        principal=Principal(A,OTHER_A,"operator",CSRF_OTHER),task_id=TASK_A)
    raise AssertionError("OTHER_PRINCIPAL_EXCHANGED_TASK")
except RecoveryRejected as error:
    assert str(error)=="REATTACH_TICKET_REJECTED"

# Verifier can revoke the attestation without a provider release.
assert verifier(SA,LA,GA,False,True) is True
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,2)) is False
assert bff(resume,(AUTH_A,CSRF_A,TASK_A,uuid4()))[0]=="provider_recheck_required"
assert verifier(SA,LA,GA,True,True) is True

# Cancellation is owner-authenticated, idempotent and does NOT fake a
# provider close or free a slot until the verifier has a separate receipt.
cancel="SELECT browser_recovery.request_cancel_own(%s,%s,%s)"
assert bff(cancel,(AUTH_B,CSRF_B,TASK_A))[0]=="not_available"
assert bff(cancel,(AUTH_OTHER,CSRF_OTHER,TASK_A))[0]=="not_available"
assert bff(cancel,(AUTH_A,CSRF_A,TASK_A))[0]=="cancel_requested"
assert bff(cancel,(AUTH_A_NEW,CSRF_A,TASK_A))[0]=="already_requested"
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,2)) is False
assert bff(resume,(AUTH_A,CSRF_A,TASK_A,uuid4()))[0]=="not_available"
with cx("postgres") as db:
    row=db.execute(
        "SELECT state FROM browser_parallel.slots WHERE slot_no=%s",(SA,)
    ).fetchone()
    assert row==("active",)
    state=db.execute(
        "SELECT state FROM browser_product.browser_tasks WHERE task_id=%s",
        (TASK_A,)
    ).fetchone()
    assert state==("running",),state

# A cancelled task before provider-create cannot consume a Steel credit,
# even if a stale worker reserved a slot in the previous queue protocol.
assert bff(cancel,(AUTH_A_NEW,CSRF_A,TASK_CANCEL))[0]=="cancel_requested"
LC,SC,GC=claim(A,TASK_CANCEL)
assert bind(AUTH_A,CSRF_A,TASK_CANCEL,SC,LC,GC)=="not_available"
assert worker(A,can_create,(TASK_CANCEL,LC,SC,GC)) is False

# A verified provider close is a SEPARATE operation. No receipt = no free.
assert worker(A,
    "SELECT browser_parallel.begin_close(%s,%s,%s,%s)",
    (TASK_A,LA,SA,GA)) is True
assert worker(A,
    "SELECT browser_parallel.finish(%s,%s,%s,%s)",
    (TASK_A,LA,SA,GA)) is False
with cx("fixture_parallel_verify") as db:
    assert db.execute(
        "SELECT browser_parallel.record_verified_release(%s,%s,%s,true,true)",
        (SA,GA,LA)
    ).fetchone()[0] is True
assert worker(A,
    "SELECT browser_parallel.finish(%s,%s,%s,%s)",
    (TASK_A,LA,SA,GA)) is True
assert worker(A,authorize_action,(TASK_A,LA,SA,GA,3)) is False

# New chat for B can also recover B; a negative receipt blocks old
# capabilities and expiry moves the provider lease to quarantine.
rb=bff(resume,(AUTH_B,CSRF_B,TASK_B,uuid4()))
assert rb==("reattach_epoch_issued",SB,GB,1),rb
assert worker(B,authorize_action,(TASK_B,LB,SB,GB,1)) is True
assert verifier(SB,LB,GB,True,False) is True
assert worker(B,authorize_action,(TASK_B,LB,SB,GB,1)) is False
assert bff(resume,(AUTH_B,CSRF_B,TASK_B,uuid4()))[0]=="provider_recheck_required"
assert verifier(SB,LB,GB,True,True) is True

with cx("postgres") as db:
    db.execute(
        "UPDATE browser_parallel.slots SET "
        "expires_at=clock_timestamp()-interval '2 seconds' WHERE slot_no=%s",
        (SB,)
    )
assert worker(B,
    "SELECT browser_parallel.quarantine_expired()",()
) >= 1
assert bff(resume,(AUTH_B,CSRF_B,TASK_B,uuid4()))[0]=="provider_recheck_required"
assert worker(B,authorize_action,(TASK_B,LB,SB,GB,1)) is False
with cx("postgres") as db:
    assert db.execute(
        "SELECT state FROM browser_parallel.slots WHERE slot_no=%s",
        (SB,)
    ).fetchone()==("quarantined",)

# Revocation and tenant membership changes are checked on EVERY request.
with cx("postgres") as db:
    db.execute(
        "UPDATE browser_auth.sessions SET revoked_at=clock_timestamp() "
        "WHERE session_digest=%s",(AUTH_A,)
    )
assert listed(AUTH_A,CSRF_A)==[]
assert bff(cancel,(AUTH_A,CSRF_A,TASK_A))[0]=="not_authorized"
with cx("postgres") as db:
    db.execute(
        "UPDATE browser_auth.memberships SET enabled=false "
        "WHERE principal_id=%s AND tenant_id=%s",(UB,B)
    )
assert listed(AUTH_B,CSRF_B)==[]
assert bff(resume,(AUTH_B,CSRF_B,TASK_B,uuid4()))[0]=="not_authorized"
with cx("postgres") as db:
    active=db.execute(
        "SELECT COUNT(*) FROM browser_parallel.slots WHERE state<>'free'"
    ).fetchone()[0]
    assert active==2,"cancelled reservation and quarantined browser remain fenced"

print("BFF_TASK_RESUME_16_CONNECTIONS_IDEMPOTENT_PASS")
print("SAME_PRINCIPAL_NEW_CHAT_REATTACH_OLD_EPOCH_DENIED_PASS")
print("CROSS_TENANT_CROSS_PRINCIPAL_REVOKED_SESSION_DENIED_PASS")
print("CANCEL_OWN_ONLY_PROVIDER_RECEIPT_AND_QUARANTINE_PASS")
print("NO_STEEL_FLOOT_RENDER_PROVIDER_OR_REAL_ACCOUNT_ACCESS")

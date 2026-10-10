"""Race 16 independent PostgreSQL connections for exactly THREE Steel slots.

Disposable PostgreSQL 16 only. No Steel, Chromium, Floot, cookies, secrets
or real users. Producer authorization is a verified per-tenant DB login role.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID,uuid4
import psycopg

DB=dict(host="127.0.0.1",port=5432,dbname="postgres",autocommit=True)
A=UUID("11111111-1111-4111-8111-111111111111")
B=UUID("22222222-2222-4222-8222-222222222222")
WA=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

# Clean ONLY isolated CI data. The live provider and customer DB must NEVER
# be reset or have their slots artificially released.
workers=[]
with psycopg.connect(**DB,user="postgres") as db:
    db.execute(
        "UPDATE browser_parallel.slots SET state='free',"
        "tenant_id=NULL,profile_id=NULL,task_id=NULL,lease_id=NULL,"
        "expires_at=NULL"
    )
    db.execute("DELETE FROM browser_product.browser_tasks")
    db.execute(
        "UPDATE browser_product.login_tenant_bindings SET enabled=true "
        "WHERE db_role IN ('fixture_parallel_a','fixture_parallel_b')"
    )
    for i in range(16):
        tenant,workspace=(A,WA) if i%2==0 else (B,WB)
        profile,task,lease=uuid4(),uuid4(),uuid4()
        db.execute(
            "INSERT INTO browser_product.profiles "
            "(tenant_id,workspace_id,profile_id,display_name,status) "
            "VALUES(%s,%s,%s,%s,'ready')",
            (tenant,workspace,profile,f"ParallelSynthetic_{i:02d}")
        )
        db.execute(
            "INSERT INTO browser_product.browser_tasks "
            "(tenant_id,workspace_id,profile_id,task_id) VALUES(%s,%s,%s,%s)",
            (tenant,workspace,profile,task)
        )
        workers.append((tenant,profile,task,lease))

barrier=Barrier(16)
def attempt(i):
    tenant,profile,task,lease=workers[i]
    role="fixture_parallel_a" if tenant==A else "fixture_parallel_b"
    with psycopg.connect(**DB,user=role) as db:
        barrier.wait(timeout=25)
        response=db.execute(
            "SELECT * FROM browser_parallel.claim(%s,%s,%s)",
            (task,lease,300)
        ).fetchone()
        return i,response

with ThreadPoolExecutor(max_workers=16) as threads:
    result=list(threads.map(attempt,range(16)))

winners=[(i,r) for i,r in result if r[0] is True and r[1] is True]
losers=[(i,r) for i,r in result if r[4]=="capacity_full" and r[0] is False]
assert len(winners)==3,(len(winners),len(losers),result)
assert len(losers)==13,(len(winners),len(losers))
assert len({r[2] for _,r in winners})==3, "TWO_JOBS_OWNED_SAME_SLOT"

for i,(granted,start,slot,generation,status) in winners:
    tenant,profile,task,lease=workers[i]
    role="fixture_parallel_a" if tenant==A else "fixture_parallel_b"
    other_role="fixture_parallel_b" if tenant==A else "fixture_parallel_a"
    with psycopg.connect(**DB,user=role) as db:
        retry=db.execute(
            "SELECT * FROM browser_parallel.claim(%s,%s,300)",
            (task,lease)
        ).fetchone()
        assert retry==(True,False,slot,generation,"existing"),retry
        assert db.execute(
            "SELECT browser_parallel.activate(%s,%s,%s,%s)",
            (task,lease,slot,generation)
        ).fetchone()[0] is True
        assert db.execute(
            "SELECT browser_parallel.activate(%s,%s,%s,%s)",
            (task,lease,slot,generation)
        ).fetchone()[0] is False
    with psycopg.connect(**DB,user=other_role) as db:
        assert db.execute(
            "SELECT browser_parallel.begin_close(%s,%s,%s,%s)",
            (task,lease,slot,generation)
        ).fetchone()[0] is False, "FOREIGN_TENANT_CLOSED_SESSION"

with psycopg.connect(**DB,user="postgres") as db:
    statuses=db.execute(
        "SELECT state,count(*) FROM browser_parallel.slots GROUP BY state"
    ).fetchall()
    assert dict(statuses)=={"active":3},statuses
    running=db.execute(
        "SELECT count(*) FROM browser_product.browser_tasks "
        "WHERE state='running'"
    ).fetchone()[0]
    assert running==3,running

# One remote session has a verified shutdown+saved profile. Its single
# available slot may be reused; the other two sessions remain active.
i,(_,_,slot,generation,_)=winners[0]
tenant,profile,task,lease=workers[i]
role="fixture_parallel_a" if tenant==A else "fixture_parallel_b"
with psycopg.connect(**DB,user=role) as db:
    assert db.execute(
        "SELECT browser_parallel.begin_close(%s,%s,%s,%s)",
        (task,lease,slot,generation)
    ).fetchone()[0] is True
    assert db.execute(
        "SELECT browser_parallel.finish(%s,%s,%s,%s)",
        (task,lease,slot,generation)
    ).fetchone()[0] is False,"UNVERIFIED_RELEASE"
with psycopg.connect(**DB,user="fixture_parallel_verify") as db:
    receipt=db.execute(
        "SELECT browser_parallel.record_verified_release(%s,%s,%s,true,true)",
        (slot,generation,lease)
    ).fetchone()[0]
    assert receipt is True
with psycopg.connect(**DB,user=role) as db:
    assert db.execute(
        "SELECT browser_parallel.finish(%s,%s,%s,%s)",
        (task,lease,slot,generation)
    ).fetchone()[0] is True

j=losers[0][0]
tenant2,profile2,task2,lease2=workers[j]
role2="fixture_parallel_a" if tenant2==A else "fixture_parallel_b"
with psycopg.connect(**DB,user=role2) as db:
    reused=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (task2,lease2)
    ).fetchone()
    assert reused[0] is True and reused[1] is True and reused[2]==slot
    assert reused[3]>generation,"STALE_FENCING_GENERATION"
    assert db.execute(
        "SELECT browser_parallel.activate(%s,%s,%s,%s)",
        (task2,lease2,slot,generation)
    ).fetchone()[0] is False,"OLD_EPOCH_REACTIVATED"
    assert db.execute(
        "SELECT browser_parallel.activate(%s,%s,%s,%s)",
        (task2,lease2,slot,reused[3])
    ).fetchone()[0] is True

# Force expiry of another independent slot, which must be quarantined but
# MUST NOT become available to the fourth provider-start attempt.
i,(_,_,old_slot,old_epoch,_)=winners[1]
oldtenant,oldprofile,oldtask,oldlease=workers[i]
old_role="fixture_parallel_a" if oldtenant==A else "fixture_parallel_b"
with psycopg.connect(**DB,user="postgres") as db:
    db.execute(
        "UPDATE browser_parallel.slots SET "
        "expires_at=clock_timestamp()-interval '1 second' "
        "WHERE slot_no=%s",(old_slot,)
    )
with psycopg.connect(**DB,user=old_role) as db:
    assert db.execute(
        "SELECT browser_parallel.quarantine_expired()"
    ).fetchone()[0]==1
    failed=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (oldtask,oldlease)
    ).fetchone()
    assert failed[4]=="quarantined" and failed[0] is False,failed

k=losers[1][0]
tk,pk,jk,lk=workers[k]
rolek="fixture_parallel_a" if tk==A else "fixture_parallel_b"
with psycopg.connect(**DB,user=rolek) as db:
    blocked=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (jk,lk)
    ).fetchone()
    assert blocked[4]=="capacity_full",blocked

with psycopg.connect(**DB,user="postgres") as db:
    slots=db.execute(
        "SELECT state,count(*) FROM browser_parallel.slots GROUP BY state"
    ).fetchall()
    assert dict(slots)=={"active":2,"quarantined":1},slots

print("PARALLEL_THREE_STEEL_SLOTS_16_DB_CONNECTIONS_PASS; no provider traffic")

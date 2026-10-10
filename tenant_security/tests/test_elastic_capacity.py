"""Elastic 5 -> 10 Steel slot admission proof on disposable PostgreSQL 16.

NO provider calls, real accounts, profile cookies, Render, Floot or Stripe.
Uses roles that the preceding three-slot SQL suite created in throwaway CI.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4
import psycopg

DB = {"host":"127.0.0.1","port":5432,"dbname":"postgres","autocommit":True}
A=UUID("11111111-1111-4111-8111-111111111111")
B=UUID("22222222-2222-4222-8222-222222222222")
WA=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ROLES={A:"fixture_parallel_a",B:"fixture_parallel_b"}

def db_for(tenant):
    return psycopg.connect(user=ROLES[tenant],**DB)

def read_capacity():
    with psycopg.connect(user="postgres",**DB) as db:
        return db.execute(
            "SELECT active_limit,provider_limit FROM browser_parallel.capacity"
        ).fetchone()

def admin_capacity(target):
    with psycopg.connect(user="postgres",**DB) as db:
        db.execute(
            "UPDATE browser_parallel.capacity SET active_limit=%s,"
            "changed_at=clock_timestamp() WHERE id=1",(target,)
        )

def race(indices,jobs):
    barrier=Barrier(len(indices))
    def attempt(i):
        tenant,profile,task,lease=jobs[i]
        with db_for(tenant) as db:
            barrier.wait(timeout=35)
            row=db.execute(
                "SELECT * FROM browser_parallel.claim(%s,%s,%s)",
                (task,lease,300)
            ).fetchone()
            return (i,row)
    with ThreadPoolExecutor(max_workers=len(indices)) as pool:
        return list(pool.map(attempt,indices))

def select(jobs,row):
    index,result=row
    tenant,profile,task,lease=jobs[index]
    return tenant,profile,task,lease,result

def activate(jobs,row):
    tenant,profile,task,lease,(ok,should_start,slot,gen,status)=select(jobs,row)
    assert ok and should_start and status=="new"
    with db_for(tenant) as db:
        assert db.execute(
            "SELECT browser_parallel.activate(%s,%s,%s,%s)",
            (task,lease,slot,gen)
        ).fetchone()[0] is True, "ACTIVATION_FAILED"
        assert db.execute(
            "SELECT browser_parallel.activate(%s,%s,%s,%s)",
            (task,lease,slot,gen)
        ).fetchone()[0] is False, "DOUBLE_ACTIVATION"

def close_with_fake_test_receipt(jobs,row):
    tenant,profile,task,lease,(ok,should_start,slot,gen,status)=select(jobs,row)
    with db_for(tenant) as db:
        assert db.execute(
            "SELECT browser_parallel.begin_close(%s,%s,%s,%s)",
            (task,lease,slot,gen)
        ).fetchone()[0] is True
        assert db.execute(
            "SELECT browser_parallel.finish(%s,%s,%s,%s)",
            (task,lease,slot,gen)
        ).fetchone()[0] is False, "UNVERIFIED_RELEASE"
    with psycopg.connect(user="fixture_parallel_verify",**DB) as db:
        assert db.execute(
            "SELECT browser_parallel.record_verified_release(%s,%s,%s,true,true)",
            (slot,gen,lease)
        ).fetchone()[0] is True
    with db_for(tenant) as db:
        assert db.execute(
            "SELECT browser_parallel.finish(%s,%s,%s,%s)",
            (task,lease,slot,gen)
        ).fetchone()[0] is True
    return slot,gen

assert read_capacity()==(5,10),"DEFAULT_CAPACITY_MUST_BE_5_OF_10"
with psycopg.connect(user="postgres",**DB) as db:
    # Clear only old synthetic fixtures; retain slot generation counters.
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
    assert db.execute("SELECT count(*) FROM browser_parallel.slots").fetchone()[0]==10

jobs=[]
with psycopg.connect(user="postgres",**DB) as db:
    for i in range(40):
        tenant,workspace=(A,WA) if i%2==0 else (B,WB)
        profile,task,lease=uuid4(),uuid4(),uuid4()
        db.execute(
            "INSERT INTO browser_product.profiles "
            "(tenant_id,workspace_id,profile_id,display_name,status) "
            "VALUES(%s,%s,%s,%s,'ready')",
            (tenant,workspace,profile,f"DynamicFixture_{i:03d}")
        )
        db.execute(
            "INSERT INTO browser_product.browser_tasks "
            "(tenant_id,workspace_id,profile_id,task_id) VALUES(%s,%s,%s,%s)",
            (tenant,workspace,profile,task)
        )
        jobs.append((tenant,profile,task,lease))

with db_for(A) as db:
    try:
        db.execute("UPDATE browser_parallel.capacity SET active_limit=10")
        raise AssertionError("TENANT_MUTATED_PROVIDER_CAPACITY")
    except psycopg.errors.InsufficientPrivilege:
        pass
    try:
        db.execute("SELECT * FROM browser_parallel.slots")
        raise AssertionError("TENANT_READ_PRIVATE_SLOTS")
    except psycopg.errors.InsufficientPrivilege:
        pass

with psycopg.connect(user="postgres",**DB) as db:
    try:
        db.execute("UPDATE browser_parallel.capacity SET active_limit=11")
        raise AssertionError("EXCEEDED_APPROVED_PROVIDER_LIMIT")
    except psycopg.errors.CheckViolation:
        pass

# Stage 1: exactly five independent sessions in the same database transaction
# protocol; all other workers must wait/deny, not exceed the configured cap.
first=race(list(range(32)),jobs)
winner1=[q for q in first if q[1][0] is True and q[1][1] is True]
loser1=[q for q in first if q[1][4]=="capacity_full"]
assert len(winner1)==5,(len(winner1),len(loser1),first)
assert len(loser1)==27,(len(winner1),len(loser1))
assert sorted(q[1][2] for q in winner1)==[1,2,3,4,5]
for row in winner1: activate(jobs,row)

i,res=winner1[0]
tenant,profile,task,lease=jobs[i]
with db_for(tenant) as db:
    again=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",(task,lease)
    ).fetchone()
    assert again[0] is True and again[1] is False
    assert again[4]=="existing",again

# A second task on exactly the same profile cannot consume a sixth slot,
# even after increasing total capacity to ten.
duplicate_task,duplicate_lease=uuid4(),uuid4()
workspace=WA if tenant==A else WB
with psycopg.connect(user="postgres",**DB) as db:
    db.execute(
        "INSERT INTO browser_product.browser_tasks "
        "(tenant_id,workspace_id,profile_id,task_id) VALUES(%s,%s,%s,%s)",
        (tenant,workspace,profile,duplicate_task)
    )
with db_for(tenant) as db:
    result=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (duplicate_task,duplicate_lease)
    ).fetchone()
    assert result[4]=="profile_busy" and result[0] is False,result

# Stage 2: an ADMINISTRATOR may increase to ten AFTER the provider tier is
# verified. This is only a simulation of that trusted approval.
admin_capacity(10)
second_indices=[i for i,_ in loser1][:20]
second=race(second_indices,jobs)
winner2=[q for q in second if q[1][0] is True and q[1][1] is True]
loser2=[q for q in second if q[1][4]=="capacity_full"]
assert len(winner2)==5,(len(winner2),len(loser2),second)
assert len(loser2)==15,(len(winner2),len(loser2))
assert sorted(q[1][2] for q in winner2)==[6,7,8,9,10]
for row in winner2: activate(jobs,row)

with psycopg.connect(user="postgres",**DB) as db:
    active=db.execute(
        "SELECT count(*) FROM browser_parallel.slots WHERE state='active'"
    ).fetchone()[0]
    running=db.execute(
        "SELECT count(*) FROM browser_product.browser_tasks WHERE state='running'"
    ).fetchone()[0]
    assert (active,running)==(10,10),(active,running)

# Lowering a policy does not kill ten already running sessions. It only
# prevents new allocations until enough independently verified releases.
admin_capacity(5)
waiting=[i for i,_ in loser2]
tenant2,profile2,task2,lease2=jobs[waiting[0]]
with db_for(tenant2) as db:
    row=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (task2,lease2)
    ).fetchone()
    assert row[4]=="capacity_full" and row[0] is False,row

combined=sorted(winner1+winner2,key=lambda q:q[1][2])
for item in combined[:6]:
    close_with_fake_test_receipt(jobs,item)

with psycopg.connect(user="postgres",**DB) as db:
    assert db.execute(
        "SELECT count(*) FROM browser_parallel.slots WHERE state='active'"
    ).fetchone()[0]==4
    assert db.execute(
        "SELECT count(*) FROM browser_parallel.slots WHERE state='free'"
    ).fetchone()[0]==6

# With four remaining sessions, policy 5 permits exactly one more.
with db_for(tenant2) as db:
    row=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (task2,lease2)
    ).fetchone()
    assert row[0] is True and row[1] is True
    assert row[2]==1 and row[3]>combined[0][1][3],row
    # Stale worker generation/lease cannot control the new session.
    old_tenant,old_profile,old_task,old_lease=jobs[combined[0][0]]
    with db_for(old_tenant) as old:
        assert old.execute(
            "SELECT browser_parallel.activate(%s,%s,%s,%s)",
            (old_task,old_lease,1,combined[0][1][3])
        ).fetchone()[0] is False
    assert db.execute(
        "SELECT browser_parallel.activate(%s,%s,%s,%s)",
        (task2,lease2,row[2],row[3])
    ).fetchone()[0] is True

# Provider uncertainty: quarantine remains counted against the cap.
unexpired=[q for q in combined[6:] if q[1][2]!=1]
assert unexpired
slot=unexpired[0][1][2]
with psycopg.connect(user="postgres",**DB) as db:
    db.execute(
        "UPDATE browser_parallel.slots SET "
        "expires_at=clock_timestamp()-interval '1 second' WHERE slot_no=%s",
        (slot,)
    )
with db_for(A) as db:
    assert db.execute("SELECT browser_parallel.quarantine_expired()").fetchone()[0]==1

remaining=[i for i,_ in loser2 if i!=waiting[0]]
with db_for(jobs[remaining[0]][0]) as db:
    target=jobs[remaining[0]]
    response=db.execute(
        "SELECT * FROM browser_parallel.claim(%s,%s,300)",
        (target[2],target[3])
    ).fetchone()
    assert response[4]=="capacity_full" and response[0] is False,response

with psycopg.connect(user="postgres",**DB) as db:
    states=dict(db.execute(
        "SELECT state,count(*) FROM browser_parallel.slots GROUP BY state"
    ).fetchall())
    assert states=={"active":4,"quarantined":1,"free":5},states

print("ELASTIC_5_OF_10_SLOTS_32_CONNECTIONS_PASS; 10 of 20 on stage 2 admitted five")
print("TENANT_ISOLATION_PROFILE_MUTEX_FENCING_RESERVE_RELEASE_QUARANTINE_PASS")
print("MOCK_ONLY_NO_PROVIDER_TRAFFIC")

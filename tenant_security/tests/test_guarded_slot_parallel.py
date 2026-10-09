"""16 concurrent tenant-bound claims vs a single durable Steel slot.

Use ONLY disposable GitHub Actions PostgreSQL. No provider API calls.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4
import psycopg

DSN = "host=127.0.0.1 port=5432 dbname=postgres"
A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
WA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WB = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PA = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PB = UUID("bbbbbbbb-0000-4000-8000-000000000002")
N = 16
jobs = [(A if i % 2 == 0 else B, uuid4(), uuid4()) for i in range(N)]

with psycopg.connect(DSN + " user=postgres", autocommit=True) as db:
    # NEVER use this code outside ephemeral PostgreSQL CI.
    db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=true "
               "WHERE db_role IN ('fixture_guarded_a','fixture_guarded_b')")
    db.execute("UPDATE browser_product.profiles SET status='ready' "
               "WHERE profile_id IN (%s,%s)", (PA, PB))
    db.execute("DELETE FROM browser_product.browser_tasks")
    db.execute("UPDATE browser_slot_guard.slots SET state='free', "
               "tenant_id=NULL,task_id=NULL,lease_id=NULL,expires_at=NULL "
               "WHERE slot_name='steel-main'")
    for tenant, task, _ in jobs:
        w,p=(WA,PA) if tenant == A else (WB,PB)
        db.execute("INSERT INTO browser_product.browser_tasks("
                   "tenant_id,workspace_id,task_id,profile_id) VALUES(%s,%s,%s,%s)",
                   (tenant,w,task,p))

barrier=Barrier(N)
def contender(i):
    tenant,task,lease=jobs[i]
    role="fixture_guarded_a" if tenant == A else "fixture_guarded_b"
    with psycopg.connect(DSN+" user="+role,autocommit=True) as db:
        barrier.wait(timeout=20)
        answer=db.execute("SELECT * FROM browser_product.claim_guarded_slot(%s,%s,300)",
                          (task,lease)).fetchone()
        return (tenant,task,lease,answer)

with ThreadPoolExecutor(max_workers=N) as pool:
    out=list(pool.map(contender,range(N)))

winners=[x for x in out if x[3][0] is True and x[3][1] is True]
losers=[x for x in out if x[3][3]=="busy"]
assert len(winners)==1 and len(losers)==15, (len(winners),len(losers))
owner,task,lease,(granted,should_start,epoch,status)=winners[0]
assert status=="new" and epoch is not None
role="fixture_guarded_a" if owner == A else "fixture_guarded_b"
not_owner="fixture_guarded_b" if owner == A else "fixture_guarded_a"

with psycopg.connect(DSN+" user="+role,autocommit=True) as db:
    again=db.execute("SELECT * FROM browser_product.claim_guarded_slot(%s,%s,300)",
                    (task,lease)).fetchone()
    assert again == (True,False,epoch,"existing"), again
    started=db.execute("SELECT browser_product.activate_guarded_slot(%s,%s,%s)",
                       (task,lease,epoch)).fetchone()[0]
    assert started, "valid tenant could not start"
    old=db.execute("SELECT browser_product.activate_guarded_slot(%s,%s,%s)",
                   (task,lease,epoch)).fetchone()[0]
    assert old is False, "idempotency yielded duplicate activation"

with psycopg.connect(DSN+" user="+not_owner,autocommit=True) as db:
    foreign=db.execute("SELECT * FROM browser_product.claim_guarded_slot(%s,%s,300)",
                       (task,lease)).fetchone()
    assert foreign[3]=="task_not_available" and foreign[0] is False,foreign
    stale=db.execute("SELECT browser_product.extend_guarded_slot(%s,%s,%s,300)",
                     (task,lease,epoch)).fetchone()[0]
    assert stale is False

with psycopg.connect(DSN+" user=postgres",autocommit=True) as db:
    row=db.execute("SELECT tenant_id,task_id,lease_id,generation,state "
                   "FROM browser_slot_guard.slots WHERE slot_name='steel-main'").fetchone()
    assert row==(owner,task,lease,epoch,"active"),row
    states=db.execute("SELECT state,COUNT(*) FROM browser_product.browser_tasks "
                      "GROUP BY state").fetchall()
    assert dict(states)=={"running":1,"queued":15},states
    db.execute("UPDATE browser_slot_guard.slots "
               "SET expires_at=clock_timestamp()-interval '1 second' "
               "WHERE slot_name='steel-main'")

i=next(i for i,(tenant,_,_) in enumerate(jobs) if tenant != owner)
other_tenant,other_task,other_lease=jobs[i]
other_role="fixture_guarded_a" if other_tenant==A else "fixture_guarded_b"
with psycopg.connect(DSN+" user="+other_role,autocommit=True) as db:
    after_expiry=db.execute("SELECT * FROM browser_product.claim_guarded_slot(%s,%s,300)",
                            (other_task,other_lease)).fetchone()
    assert after_expiry[3]=="quarantined" and after_expiry[0] is False,after_expiry

with psycopg.connect(DSN+" user=postgres",autocommit=True) as db:
    status=db.execute("SELECT state FROM browser_slot_guard.slots").fetchone()[0]
    assert status=="quarantined",status

print("GUARDED_TENANT_SLOT_16_CONNECTIONS_PASS; synthetic only")

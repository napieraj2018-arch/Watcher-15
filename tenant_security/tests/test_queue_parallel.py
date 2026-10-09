"""16 isolated PostgreSQL connections race against one tenant quota."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID,uuid4
import psycopg

conn=dict(host="127.0.0.1",port=5432,dbname="postgres",autocommit=True)
a=UUID("11111111-1111-4111-8111-111111111111")
b=UUID("22222222-2222-4222-8222-222222222222")
wa=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
wb=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
pa=UUID("aaaaaaaa-0000-4000-8000-000000000001")
pb=UUID("bbbbbbbb-0000-4000-8000-000000000002")
with psycopg.connect(**conn,user="postgres") as db:
    # Only ephemeral fixture data. Never run on real user accounts.
    db.execute("DELETE FROM browser_product.browser_tasks WHERE tenant_id=%s",(a,))
    db.execute("UPDATE browser_product.login_tenant_bindings SET enabled=true WHERE db_role='fixture_tenant_b'")

barrier=Barrier(16)
def attempt(_):
    ident=uuid4()
    with psycopg.connect(**conn,user="fixture_tenant_a") as db:
        barrier.wait(timeout=15)
        code,state=db.execute(
            "SELECT * FROM browser_product.enqueue_task(%s,%s,%s)",
            (wa,pa,ident)
        ).fetchone()
        return ident,code,state

with ThreadPoolExecutor(max_workers=16) as pool:
    responses=list(pool.map(attempt,range(16)))
created=[x for x in responses if x[1]=="created"]
denied=[x for x in responses if x[1]=="quota_reached"]
assert len(created)==10, f"Quota race: {len(created)} created, expected 10"
assert len(denied)==6, f"Quota race: {len(denied)} rejected, expected 6"
assert all(x[2]=="queued" for x in created)
assert all(x[2] is None for x in denied)

with psycopg.connect(**conn,user="fixture_tenant_a") as db:
    code,state=db.execute("SELECT * FROM browser_product.enqueue_task(%s,%s,%s)",(wa,pa,created[0][0])).fetchone()
    assert (code,state)==("existing","queued"),(code,state)
with psycopg.connect(**conn,user="fixture_tenant_b") as db:
    code,state=db.execute("SELECT * FROM browser_product.enqueue_task(%s,%s,%s)",(wb,pb,uuid4())).fetchone()
    assert (code,state)==("created","queued"),(code,state)
    code,state=db.execute("SELECT * FROM browser_product.enqueue_task(%s,%s,%s)",(wa,pa,uuid4())).fetchone()
    assert (code,state)==("profile_not_available",None),(code,state)

with psycopg.connect(**conn,user="postgres") as db:
    a_count=db.execute("SELECT COUNT(*) FROM browser_product.browser_tasks WHERE tenant_id=%s AND state='queued'",(a,)).fetchone()[0]
    b_count=db.execute("SELECT COUNT(*) FROM browser_product.browser_tasks WHERE tenant_id=%s AND state='queued'",(b,)).fetchone()[0]
    assert a_count==10, a_count
    assert b_count==2, b_count  # one original fixture, one new B
print("TENANT_ATOMIC_QUEUE_16_CONNECTIONS_PASS")

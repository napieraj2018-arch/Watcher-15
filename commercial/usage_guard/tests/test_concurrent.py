"""Only an ephemeral PostgreSQL 16 database, never real Steel or billing."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4
import psycopg

DB = {"host":"127.0.0.1","port":5432,"dbname":"postgres","autocommit":True}
tenant_a = UUID("11111111-1111-4111-8111-111111111111")
tenant_b = UUID("22222222-2222-4222-8222-222222222222")
with psycopg.connect(user="postgres",**DB) as conn:
    conn.execute("DELETE FROM browser_meter.jobs")
    conn.execute(
        "UPDATE browser_meter.policies SET status='active', "
        "monthly_cap_cents=1000,reserve_per_job_cents=30,max_open_jobs=4 "
        "WHERE tenant_id=%s",(tenant_a,)
    )
    conn.execute(
        "UPDATE browser_meter.policies SET status='active', "
        "monthly_cap_cents=100,reserve_per_job_cents=20,max_open_jobs=2 "
        "WHERE tenant_id=%s",(tenant_b,)
    )

barrier=Barrier(16)
def attempt(_):
    job=uuid4()
    with psycopg.connect(user="fixture_meter_a",**DB) as conn:
        barrier.wait(timeout=20)
        result=conn.execute(
            "SELECT code,may_start FROM browser_meter.reserve(%s)",(job,)
        ).fetchone()
        return job,result

with ThreadPoolExecutor(max_workers=16) as pool:
    results=list(pool.map(attempt,range(16)))
accepted=[row for row in results if row[1]==("reserved",True)]
denied=[row for row in results if row[1]==("concurrency_cap",False)]
assert len(accepted)==4,(len(accepted),len(denied))
assert len(denied)==12,(len(accepted),len(denied))

with psycopg.connect(user="fixture_meter_a",**DB) as conn:
    duplicate=conn.execute(
        "SELECT * FROM browser_meter.reserve(%s)",(accepted[0][0],)
    ).fetchone()
    assert duplicate==("already_recorded",False),duplicate
    balance=conn.execute(
        "SELECT * FROM browser_meter.my_balance()"
    ).fetchone()
    assert balance[2]==120 and balance[3]==4,balance

with psycopg.connect(user="fixture_meter_b",**DB) as conn:
    own=conn.execute(
        "SELECT * FROM browser_meter.reserve(%s)",(uuid4(),)
    ).fetchone()
    assert own==("reserved",True),own

with psycopg.connect(user="postgres",**DB) as conn:
    count_a=conn.execute(
        "SELECT count(*) FROM browser_meter.jobs WHERE tenant_id=%s",
        (tenant_a,)
    ).fetchone()[0]
    assert count_a==4,count_a
print("MOCK_VENDOR_BUDGET_PARALLEL_16_PASS")

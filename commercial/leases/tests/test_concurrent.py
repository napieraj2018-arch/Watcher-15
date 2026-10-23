"""Concurrent multi-connection claims on THROWAWAY Postgres only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4
import psycopg

DSN = "host=127.0.0.1 port=5432 dbname=postgres user=postgres"
N = 16
TENANTS = [UUID("11111111-1111-4111-8111-111111111111"),
           UUID("22222222-2222-4222-8222-222222222222")]
with psycopg.connect(DSN, autocommit=True) as connection:
    with connection.cursor() as c:
        # Only reset fixture data in this disposable CI service.
        c.execute("""UPDATE browser_slot_guard.slots SET state='free',
          tenant_id=NULL,task_id=NULL,lease_id=NULL,expires_at=NULL
          WHERE slot_name='steel-main'""")
barrier = Barrier(N)

def contender(n):
    tenant = TENANTS[n % 2]
    task, lease = uuid4(), uuid4()
    with psycopg.connect(DSN, autocommit=True) as connection:
        with connection.cursor() as c:
            c.execute("SET SESSION AUTHORIZATION fixture_slot_worker")
            barrier.wait(timeout=15)
            c.execute("SELECT * FROM browser_slot_guard.claim_slot(%s,%s,%s,300)",
                      (tenant,task,lease))
            record = c.fetchone()
            return tenant,task,lease,record

with ThreadPoolExecutor(max_workers=N) as pool:
    results = list(pool.map(contender, range(N)))
winners = [x for x in results if x[3][0] is True and x[3][1] is True]
assert len(winners) == 1, "A global Steel slot may have only one starter"
assert sum(1 for x in results if x[3][0] is False) == N-1
assert all(len(x[3]) == 4 for x in results), "Do not leak provider IDs"

tenant,task,lease,(granted,should_start,generation,status) = winners[0]
with psycopg.connect(DSN, autocommit=True) as connection:
    with connection.cursor() as c:
        c.execute("SET SESSION AUTHORIZATION fixture_slot_worker")
        c.execute("SELECT * FROM browser_slot_guard.claim_slot(%s,%s,%s,300)",
                  (tenant,task,lease))
        duplicate = c.fetchone()
        assert duplicate == (True,False,generation,"existing"), duplicate
        c.execute("SELECT browser_slot_guard.activate_slot(%s,%s,%s,%s)",
                  (tenant,task,lease,generation))
        assert c.fetchone()[0] is True
        c.execute("SELECT browser_slot_guard.begin_close(%s,%s,%s,%s)",
                  (tenant,task,lease,generation))
        assert c.fetchone()[0] is True
        c.execute("SELECT browser_slot_guard.finish_slot(%s,%s,%s,%s)",
                  (tenant,task,lease,generation))
        assert c.fetchone()[0] is False, "No independently verified receipt"
print("DURABLE_LEASE_PARALLEL_16_PASS; no live Steel or Floot touched")

"""Postgres adapter; commit must succeed before returning HTTP 200 to Stripe.

The injected connection factory must use a DB role with only EXECUTE on
stripe_billing.ingest. NO Stripe API key, customer credential or live DSN here.
"""
from .inbox import ValidatedEvent


class PgEventInbox:
    def __init__(self, connect):
        self._connect = connect

    def insert(self, event: ValidatedEvent) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT stripe_billing.ingest(%s,%s,%s,%s,%s,%s)",
                    (event.livemode, event.id, event.type, event.customer_id,
                     event.object_id, event.digest),
                )
                row = cursor.fetchone()
                result = row[0] if row else "unavailable"
            # Context commits here; failure raises and webhook returns 503.
        return result

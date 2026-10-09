"""Offline erasure tests with synthetic tenant/profile IDs, no real Steel calls."""
from __future__ import annotations
import asyncio
import json
import unittest

from commercial.profile_erasure import (
    ErasureCoordinator, ErasureError, Principal, Request, OTHER_SOURCES
)

TENANT="tenant-test-A"
USER="user-test-A"
PROFILE="11111111-1111-4111-8111-111111111111"
PROVIDER="22222222-2222-4222-8222-222222222222"

class FakeBackend:
    def __init__(self):
        self.owner=TENANT
        self.authorized_value=True
        self.session="empty"
        self.locked=False
        self.lock_ack=True
        self.lock_sticks=True
        self.provider_id=PROVIDER
        self.provider_present=True
        self.get_states=[]
        self.ack="accepted"
        self.purge_ack=True
        self.purge_sticks=True
        self.sources={k:True for k in OTHER_SOURCES}
        self.visible=True
        self.final_ack=True
        self.final_verify=True
        self.final=False
        self.events=[]
        self.fail_source=None
        self.release_lock_on_source=None
        self.raise_in=None

    async def authorized(self,principal,profile_id):
        self.events.append("authorized")
        return self.authorized_value and principal.tenant_id==self.owner and profile_id==PROFILE

    async def sessions_state(self,tenant,profile):
        self.events.append("sessions")
        return self.session

    async def lock_profile(self,tenant,profile):
        self.events.append("lock")
        if self.lock_ack and self.lock_sticks:
            self.locked=True
        return self.lock_ack

    async def is_locked(self,tenant,profile):
        self.events.append("verify_lock")
        return self.locked

    async def provider_profile_id(self,tenant,profile):
        self.events.append("mapping")
        return self.provider_id

    async def provider_exists(self,provider_id):
        self.events.append("provider_exists")
        if self.get_states:
            return self.get_states.pop(0)
        return self.provider_present

    async def provider_delete(self,provider_id):
        self.events.append("provider_delete")
        if self.raise_in=="provider_delete":
            raise RuntimeError("SYNTHETIC_PROVIDER_API_TOKEN")
        if self.ack=="accepted":
            self.provider_present=False
        return self.ack

    async def contains(self,tenant,profile,source):
        self.events.append("contains:"+source)
        if self.fail_source==source and not self.visible:
            return None
        return self.sources[source]

    async def purge(self,tenant,profile,source):
        self.events.append("purge:"+source)
        if self.raise_in==source:
            raise RuntimeError("SYNTHETIC_CREDENTIALS_SHOULD_NEVER_LEAK")
        if self.fail_source==source:
            return False
        if self.purge_sticks:
            self.sources[source]=False
        if self.release_lock_on_source==source:
            self.locked=False
        return self.purge_ack

    async def finalize(self,tenant,profile):
        self.events.append("finalize")
        if self.final_ack:
            self.final=True
        return self.final_ack

    async def final_tombstone_verified(self,tenant,profile):
        self.events.append("verify_final")
        return bool(self.final and self.final_verify)

def request(tenant=TENANT,step_up=True):
    return Request(Principal(tenant,USER,step_up),PROFILE,"erase_permanently")

class ErasureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend=FakeBackend()
        self.coordinator=ErasureCoordinator(self.backend)
    async def execute(self,r=None):
        return await self.coordinator.execute(r or request())

    async def test_complete_requires_provider_and_all_sources_gone(self):
        result=await self.execute()
        self.assertTrue(result.complete)
        self.assertEqual(result.status,"completed")
        self.assertFalse(self.backend.provider_present)
        self.assertFalse(any(self.backend.sources.values()))
        self.assertTrue(self.backend.final)

    async def test_no_step_up_no_action(self):
        with self.assertRaisesRegex(ErasureError,"STEP_UP_AUTH_REQUIRED"):
            await self.execute(request(step_up=False))
        self.assertEqual(self.backend.events,[])

    async def test_other_tenant_not_allowed_no_enumeration(self):
        with self.assertRaisesRegex(ErasureError,"PROFILE_NOT_ACCESSIBLE"):
            await self.execute(request(tenant="tenant-test-B"))
        self.assertEqual(self.backend.events,["authorized"])

    async def test_unverified_authorization_denied(self):
        self.backend.authorized_value=False
        with self.assertRaisesRegex(ErasureError,"PROFILE_NOT_ACCESSIBLE"):
            await self.execute()
        self.assertNotIn("lock",self.backend.events)

    async def test_authorization_exception_sanitized(self):
        async def fail(*args):
            raise RuntimeError("SECRET_SYNTHETIC_AUTHENTICATION_TOKEN")
        self.backend.authorized=fail
        with self.assertRaises(ErasureError) as ctx:
            await self.execute()
        self.assertEqual(str(ctx.exception),"AUTHORIZATION_UNVERIFIED")

    async def test_active_session_prevents_deletion(self):
        self.backend.session="active"
        result=await self.execute()
        self.assertEqual(result.phase,"ACTIVE_OR_UNKNOWN_SESSIONS")
        self.assertFalse(self.backend.locked)
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_unknown_session_prevents_deletion(self):
        self.backend.session="unknown"
        self.assertEqual((await self.execute()).status,"blocked")
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_prelocked_profile_still_checks_active_sessions(self):
        self.backend.locked=True
        self.backend.session="active"
        result=await self.execute()
        self.assertEqual(result.phase,"ACTIVE_OR_UNKNOWN_SESSIONS")
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_refused_lock_blocks_provider(self):
        self.backend.lock_ack=False
        result=await self.execute()
        self.assertEqual(result.phase,"COULD_NOT_FENCE_PROFILE")
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_lock_confirmation_required(self):
        self.backend.lock_sticks=False
        result=await self.execute()
        self.assertEqual(result.phase,"LOCK_NOT_VERIFIED")
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_mapping_missing_cannot_claim_erasure(self):
        self.backend.provider_id=None
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_MAPPING_UNVERIFIED")
        self.assertFalse(result.complete)
        self.assertTrue(self.backend.locked)

    async def test_malformed_provider_id_blocks(self):
        self.backend.provider_id="SYNTHETIC_NOT_A_UUID"
        self.assertEqual((await self.execute()).phase,"PROVIDER_MAPPING_UNVERIFIED")

    async def test_provider_visibility_unknown(self):
        self.backend.get_states=[None]
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_STATE_UNKNOWN")
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_unsupported_provider_delete_blocks_and_preserves_registry(self):
        self.backend.ack="unsupported"
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_ERASURE_UNSUPPORTED")
        self.assertTrue(all(self.backend.sources.values()))
        self.assertNotIn("finalize",self.backend.events)

    async def test_ambiguous_provider_ack_is_not_accepted(self):
        self.backend.ack="uncertain"
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_DELETE_UNVERIFIED")
        self.assertFalse(any(k.startswith("purge:") for k in self.backend.events))

    async def test_unknown_delete_ack_fails_closed(self):
        self.backend.ack="OK_BUT_NOT_DEFINED"
        self.assertEqual((await self.execute()).phase,"PROVIDER_DELETE_UNVERIFIED")

    async def test_provider_success_not_enough_without_readback(self):
        self.backend.get_states=[True,True]
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_DELETION_NOT_VERIFIED")
        self.assertNotIn("finalize",self.backend.events)
        self.assertTrue(all(self.backend.sources.values()))

    async def test_readback_unknown_does_not_purge(self):
        self.backend.get_states=[True,None]
        result=await self.execute()
        self.assertEqual(result.phase,"PROVIDER_DELETION_NOT_VERIFIED")
        self.assertFalse(any(x.startswith("purge:") for x in self.backend.events))

    async def test_provider_already_gone_can_finish_after_local_checks(self):
        self.backend.provider_present=False
        result=await self.execute()
        self.assertTrue(result.complete)
        self.assertNotIn("provider_delete",self.backend.events)

    async def test_missing_backup_visibility_is_not_zero(self):
        self.backend.fail_source="portable_snapshot"
        self.backend.visible=False
        result=await self.execute()
        self.assertEqual(result.phase,"STORAGE_VISIBILITY_UNKNOWN")
        self.assertNotIn("finalize",self.backend.events)

    async def test_purge_not_acknowledged_blocks(self):
        self.backend.fail_source="credential_vault"
        result=await self.execute()
        self.assertEqual(result.phase,"STORAGE_PURGE_NOT_ACKNOWLEDGED")
        self.assertFalse(result.complete)

    async def test_purge_ack_without_readback_does_not_count(self):
        self.backend.purge_sticks=False
        result=await self.execute()
        self.assertEqual(result.phase,"STORAGE_PURGE_NOT_VERIFIED")
        self.assertNotIn("finalize",self.backend.events)

    async def test_lease_lock_lost_mid_erasure_blocks(self):
        self.backend.release_lock_on_source="portable_snapshot"
        result=await self.execute()
        self.assertEqual(result.phase,"LOCK_LOST_DURING_ERASURE")
        self.assertNotIn("finalize",self.backend.events)

    async def test_finalization_not_acknowledged(self):
        self.backend.final_ack=False
        result=await self.execute()
        self.assertEqual(result.phase,"FINAL_TOMBSTONE_NOT_ACKNOWLEDGED")

    async def test_finalization_not_read_back(self):
        self.backend.final_verify=False
        result=await self.execute()
        self.assertEqual(result.phase,"FINAL_TOMBSTONE_NOT_VERIFIED")
        self.assertFalse(result.complete)

    async def test_retry_after_partial_source_failure(self):
        self.backend.fail_source="portable_snapshot"
        result=await self.execute()
        self.assertEqual(result.status,"paused")
        self.backend.fail_source=None
        replay=await self.execute()
        self.assertTrue(replay.complete)
        self.assertEqual(self.backend.events.count("provider_delete"),1)

    async def test_completion_replay_does_not_repeat_provider_delete(self):
        first=await self.execute()
        second=await self.execute()
        self.assertTrue(first.complete and second.complete)
        self.assertEqual(self.backend.events.count("provider_delete"),1)

    async def test_provider_exception_does_not_return_secret(self):
        self.backend.raise_in="provider_delete"
        result=await self.execute()
        output=json.dumps(result.as_public_json())
        self.assertEqual(result.status,"paused")
        self.assertNotIn("SYNTHETIC_PROVIDER_API_TOKEN",output)
        self.assertTrue(all(self.backend.sources.values()))

    async def test_vault_exception_does_not_return_secret(self):
        self.backend.raise_in="credential_vault"
        result=await self.execute()
        self.assertEqual(result.status,"paused")
        self.assertNotIn("CREDENTIALS_SHOULD_NEVER_LEAK",json.dumps(result.as_public_json()))

    async def test_public_receipt_hides_raw_identifiers(self):
        result=await self.execute()
        receipt=json.dumps(result.as_public_json())
        for secret in (TENANT,USER,PROFILE,PROVIDER):
            self.assertNotIn(secret,receipt)

    async def test_provider_deleted_before_any_local_backup(self):
        await self.execute()
        i=self.backend.events.index("provider_exists",self.backend.events.index("provider_delete"))
        j=next(n for n,event in enumerate(self.backend.events) if event.startswith("purge:"))
        self.assertLess(i,j)

    async def test_finalization_after_every_source(self):
        await self.execute()
        stop=self.backend.events.index("finalize")
        self.assertEqual(sum(x.startswith("purge:") for x in self.backend.events),len(OTHER_SOURCES))
        self.assertLess(max(i for i,x in enumerate(self.backend.events) if x.startswith("purge:")),stop)

    async def test_parallel_attempts_do_not_delete_twice(self):
        a,b=await asyncio.gather(self.execute(),self.execute())
        self.assertTrue(a.complete and b.complete)
        self.assertEqual(self.backend.events.count("provider_delete"),1)

    async def test_invalid_confirmation_rejected(self):
        with self.assertRaisesRegex(ErasureError,"INVALID_ERASURE_REQUEST"):
            Request(Principal(TENANT,USER,True),PROFILE,"erase")

    async def test_invalid_uuid_rejected(self):
        with self.assertRaisesRegex(ErasureError,"INVALID_ERASURE_REQUEST"):
            Request(Principal(TENANT,USER,True),"../test","erase_permanently")

    async def test_boolean_principal_rejected(self):
        with self.assertRaisesRegex(ErasureError,"INVALID_PRINCIPAL"):
            Principal(TENANT,USER,1)

if __name__=="__main__":
    unittest.main(verbosity=2)

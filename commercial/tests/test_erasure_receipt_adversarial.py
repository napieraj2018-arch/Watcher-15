"""Adversarial offline erasure acceptance tests; no Steel/Floot network calls."""
from __future__ import annotations
import json
import unittest

from commercial.profile_erasure import ErasureCoordinator, ErasureError
from commercial.tests.test_profile_erasure import FakeBackend, request

class IndependentEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b=FakeBackend()
        self.coordinator=ErasureCoordinator(self.b)

    async def run_erasure(self):
        return await self.coordinator.execute(request())

    async def test_boolean_step_up_from_client_not_sufficient(self):
        self.b.step_up_value=False
        with self.assertRaisesRegex(ErasureError,"STEP_UP_NOT_VERIFIED"):
            await self.run_erasure()
        self.assertEqual(self.b.events,["authorized","trusted_step_up"])
        self.assertFalse(self.b.locked)

    async def test_step_up_exception_hides_secret_and_no_mutation(self):
        self.b.step_up_error=True
        with self.assertRaises(ErasureError) as caught:
            await self.run_erasure()
        self.assertEqual(str(caught.exception),"STEP_UP_VERIFICATION_UNAVAILABLE")
        self.assertNotIn("PRIVATE",str(caught.exception))
        self.assertNotIn("provider_delete",self.b.events)

    async def test_step_up_returns_none_or_int_fails_closed(self):
        async def unexpected(*_args):
            return 1
        self.b.verify_fresh_step_up=unexpected
        with self.assertRaisesRegex(ErasureError,"STEP_UP_NOT_VERIFIED"):
            await self.run_erasure()
        self.assertFalse(self.b.locked)

    async def test_no_independent_receipt_no_completion(self):
        self.b.receipts_value=False
        result=await self.run_erasure()
        self.assertEqual(result.status,"paused")
        self.assertEqual(result.phase,"ERASURE_RECEIPTS_UNVERIFIED")
        self.assertFalse(result.complete)
        self.assertTrue(self.b.final)

    async def test_signed_receipt_provider_error_remains_redacted(self):
        self.b.receipts_error=True
        result=await self.run_erasure()
        self.assertEqual(result.status,"paused")
        self.assertFalse(result.complete)
        self.assertNotIn("FAKE_PROVIDER_CREDENTIAL_TOKEN",json.dumps(result.as_public_json()))

    async def test_replay_tombstone_alone_not_completion(self):
        self.b.final=True
        self.b.receipts_value=False
        result=await self.run_erasure()
        self.assertEqual(result.phase,"ERASURE_RECEIPTS_UNVERIFIED")
        self.assertNotIn("provider_delete",self.b.events)

    async def test_old_tombstone_with_native_provider_resurrected_pauses(self):
        self.b.final=True
        self.b.provider_present=True
        for k in self.b.sources:self.b.sources[k]=False
        result=await self.run_erasure()
        self.assertEqual(result.phase,"ERASURE_RECEIPTS_UNVERIFIED")
        self.assertFalse(result.complete)

    async def test_old_tombstone_with_backup_resurrected_pauses(self):
        self.b.final=True
        self.b.provider_present=False
        for k in self.b.sources:self.b.sources[k]=False
        self.b.sources["archived_versions"]=True
        result=await self.run_erasure()
        self.assertEqual(result.phase,"ERASURE_RECEIPTS_UNVERIFIED")
        self.assertFalse(result.complete)

    async def test_full_receipt_allows_replay_without_duplicate_delete(self):
        first=await self.run_erasure()
        again=await self.run_erasure()
        self.assertTrue(first.complete and again.complete)
        self.assertEqual(self.b.events.count("verify_independent_receipts"),2)
        self.assertEqual(self.b.events.count("provider_delete"),1)

    async def test_missing_receipt_can_be_reconciled_without_resubmitting_delete(self):
        self.b.receipts_value=False
        first=await self.run_erasure()
        self.assertFalse(first.complete)
        self.b.receipts_value=True
        second=await self.run_erasure()
        self.assertTrue(second.complete)
        self.assertEqual(self.b.events.count("provider_delete"),1)

    async def test_forged_receipt_return_integer_is_denied(self):
        async def bad_receipt(*_args):
            return 1
        self.b.erasure_receipts_verified=bad_receipt
        result=await self.run_erasure()
        self.assertEqual(result.phase,"ERASURE_RECEIPTS_UNVERIFIED")

    async def test_step_up_evidence_checked_before_lease_and_provider(self):
        await self.run_erasure()
        self.assertLess(self.b.events.index("trusted_step_up"),self.b.events.index("lock"))
        self.assertLess(self.b.events.index("trusted_step_up"),self.b.events.index("provider_delete"))

    async def test_no_erasure_evidence_in_public_report(self):
        result=await self.run_erasure()
        serialized=json.dumps(result.as_public_json())
        for forbidden in ("tenant-test", "user-test", "11111111", "22222222",
                          "credential_vault", "provider_profile_ref"):
            self.assertNotIn(forbidden,serialized)
        self.assertEqual(set(result.as_public_json()),{"status","phase","complete"})

if __name__=="__main__":
    unittest.main(verbosity=2)

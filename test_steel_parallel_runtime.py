"""Steel parallel owner beta, with 0 real remote API calls."""
from __future__ import annotations
import asyncio
import os
import unittest
from unittest.mock import patch

from steel_runtime import Engine, SteelFailure, parallel_session_capacity
from test_steel_singleflight import FakeEngine, FakeChromium


class Configuration(unittest.TestCase):
    def test_one_by_default(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(parallel_session_capacity(),1)

    def test_reject_two_without_strict_guard(self):
        for guard in ("", "0", "1", "probe"):
            with self.subTest(mode=guard),patch.dict(os.environ,{
                "AI_BROWSER_PARALLEL_SESSIONS":"5",
                "AI_BROWSER_SESSION_GUARD":guard,
                "AI_BROWSER_PARALLEL_OWNER_BETA":"1"},clear=True):
                with self.assertRaisesRegex(SteelFailure,"GUARD_REQUIRED"):
                    parallel_session_capacity()

    def test_reject_guard_without_beta_owner_authorization(self):
        with patch.dict(os.environ,{
                "AI_BROWSER_PARALLEL_SESSIONS":"5",
                "AI_BROWSER_SESSION_GUARD":"multi"
                },clear=True):
            with self.assertRaisesRegex(SteelFailure,"BETA_REQUIRED"):
                parallel_session_capacity()

    def test_allow_up_to_five_explicit(self):
        for count in range(1,6):
            with self.subTest(capacity=count),patch.dict(os.environ,{
                "AI_BROWSER_PARALLEL_SESSIONS":str(count),
                "AI_BROWSER_SESSION_GUARD":"multi",
                "AI_BROWSER_PARALLEL_OWNER_BETA":"1"},clear=True):
                self.assertEqual(parallel_session_capacity(),count)

    def test_reject_invalid_configuration_without_fallback(self):
        for count in ("0","-1","6","10","01","five","1.5"," 5","5 ",""):
            with self.subTest(value=count),patch.dict(os.environ,{
                "AI_BROWSER_PARALLEL_SESSIONS":count,
                "AI_BROWSER_SESSION_GUARD":"multi",
                "AI_BROWSER_PARALLEL_OWNER_BETA":"1"},clear=True):
                with self.assertRaisesRegex(SteelFailure,"CONFIG_INVALID"):
                    parallel_session_capacity()


class RealEngineContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key=patch.dict(os.environ,{"STEEL_API_KEY":"SYNTHETIC_NOT_A_REAL_KEY"})
        self.key.start()

    def tearDown(self):
        self.key.stop()

    async def test_five_distinct_remote_session_handles_and_sixth_rejected(self):
        engine,chrome=FakeEngine(),FakeChromium()
        engine.max_sessions=5
        remotes=await asyncio.gather(*(
            engine.launch(chrome) for _ in range(5)))
        self.assertEqual(len(engine.remote),5)
        self.assertEqual(len({r.remote_id for r in remotes}),5)
        self.assertEqual(engine.creates,5)
        self.assertEqual(chrome.attempts,5)
        with self.assertRaisesRegex(SteelFailure,"STEEL_SESSION_LIMIT_5"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates,5)
        await asyncio.gather(*(r.close() for r in remotes))
        self.assertEqual(engine.releases,5)
        self.assertEqual(engine.remote,{})

    async def test_released_slot_reused_without_touching_other_four(self):
        engine,chrome=FakeEngine(),FakeChromium()
        engine.max_sessions=5
        remotes=[await engine.launch(chrome) for _ in range(5)]
        occupied_ids={r.remote_id for r in remotes[1:]}
        await remotes[0].close()
        sixth=await engine.launch(chrome)
        self.assertEqual(len(engine.remote),5)
        self.assertEqual(occupied_ids & set(engine.remote),occupied_ids)
        self.assertNotIn(remotes[0].remote_id,engine.remote)
        await asyncio.gather(*(r.close() for r in remotes[1:]),sixth.close())
        self.assertEqual(engine.remote,{})

    async def test_uncertain_release_prevents_costly_sixth_create(self):
        engine,chrome=FakeEngine(),FakeChromium()
        engine.max_sessions=5
        remotes=[await engine.launch(chrome) for _ in range(5)]
        engine.fail_release=True
        with self.assertRaisesRegex(SteelFailure,"STEEL_REMOTE_RELEASE_UNCONFIRMED"):
            await remotes[0].close()
        self.assertTrue(engine._quarantined)
        self.assertEqual(len(engine.remote),5)
        with self.assertRaisesRegex(SteelFailure,"STEEL_SESSION_QUARANTINED"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates,5)
        engine.fail_release=False
        await asyncio.gather(*(r.close() for r in remotes[1:]))
        self.assertEqual(len(engine.remote),1,"uncertain release never silently freed")

    async def test_create_is_serialized_even_when_capacity_is_five(self):
        engine,chrome=FakeEngine(),FakeChromium()
        engine.max_sessions=5
        engine.block_create=True
        first=asyncio.create_task(engine.launch(chrome))
        await asyncio.wait_for(engine.create_entered.wait(),2)
        second=asyncio.create_task(engine.launch(chrome))
        await asyncio.sleep(0.025)
        self.assertEqual(engine.creates,1)
        engine.create_continue.set()
        one,two=await asyncio.wait_for(asyncio.gather(first,second),3)
        self.assertEqual(engine.creates,2)
        await asyncio.gather(one.close(),two.close())

if __name__=="__main__":
    unittest.main(verbosity=2)

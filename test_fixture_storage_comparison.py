"""Safe, SteelSelfTest-only comparisons. No provider call or customer cookies."""
import json
import unittest
from types import SimpleNamespace

from steel_context_fix import (
    synthetic_fixture_apply_comparison,
    synthetic_fixture_page_context_evidence,
)
from test_synthetic_fixture_exact import fixture


class CompareApply(unittest.TestCase):
    def test_identical_cookie_and_local_storage_are_both_observed(self):
        proposed=fixture('same-synthetic','same-synthetic')
        result=synthetic_fixture_apply_comparison(proposed, proposed)
        self.assertEqual(result,{
            'available':True,
            'cookie_matches_proposed':True,
            'storage_matches_proposed':True,
        })

    def test_stale_cookie_with_fresh_localstorage_is_identified(self):
        proposed=fixture('fresh','fresh')
        actual=fixture('stale','fresh')
        result=synthetic_fixture_apply_comparison(actual, proposed)
        self.assertFalse(result['cookie_matches_proposed'])
        self.assertTrue(result['storage_matches_proposed'])

    def test_fresh_cookie_with_stale_localstorage_is_identified(self):
        proposed=fixture('fresh','fresh')
        actual=fixture('fresh','stale')
        result=synthetic_fixture_apply_comparison(actual, proposed)
        self.assertTrue(result['cookie_matches_proposed'])
        self.assertFalse(result['storage_matches_proposed'])

    def test_unavailable_state_cannot_be_reported_as_success(self):
        proposed=fixture('fresh','fresh')
        for actual in (None, [], {'cookies':[],'origins':[]}, {'cookies':{}}):
            value=synthetic_fixture_apply_comparison(actual, proposed)
            self.assertFalse(value['cookie_matches_proposed'])
            self.assertFalse(value['storage_matches_proposed'])
            self.assertEqual(set(value),{
                'available','cookie_matches_proposed','storage_matches_proposed'
            })

    def test_no_marker_secret_is_returned_in_comparisons(self):
        marker='UNIQUE_TEST_VALUE_NEVER_RETURNED'
        state=fixture(marker,marker)
        serialized=json.dumps(synthetic_fixture_apply_comparison(state,state))
        self.assertNotIn(marker,serialized)
        self.assertNotIn('aibrowser_test_cookie',serialized)


class PageContextReadback(unittest.IsolatedAsyncioTestCase):
    async def test_matching_post_navigation_context_reports_only_counts(self):
        class Context:
            async def storage_state(self,**kwargs):
                self.kwargs=kwargs
                return fixture('dummy','dummy')
        context=Context()
        page=SimpleNamespace(url='https://ai-browser-vault.floot.app/browser-check',
                             context=context)
        result=await synthetic_fixture_page_context_evidence(page)
        self.assertEqual(result['status'],'observed')
        self.assertTrue(result['exact_pair_matches'])
        self.assertEqual(result['cookie_readable_count'],1)
        self.assertEqual(result['storage_exact_key_count'],1)
        self.assertEqual(context.kwargs,{'indexed_db':True})
        self.assertNotIn('dummy',json.dumps(result))

    async def test_post_navigation_context_detects_mismatch(self):
        class Context:
            async def storage_state(self,**kwargs):
                return fixture('old','new')
        page=SimpleNamespace(url='https://ai-browser-vault.floot.app/browser-check',
                             context=Context())
        result=await synthetic_fixture_page_context_evidence(page)
        self.assertEqual(result['status'],'observed')
        self.assertFalse(result['exact_pair_matches'])

    async def test_nonfixture_page_never_reads_context(self):
        class Context:
            async def storage_state(self,**kwargs):
                raise AssertionError('never inspect real website browser storage')
        page=SimpleNamespace(url='https://www.facebook.com/',context=Context())
        self.assertEqual(await synthetic_fixture_page_context_evidence(page),
                         {'status':'not_fixture_page'})

    async def test_failed_browser_readback_returns_only_fixed_status(self):
        class Context:
            async def storage_state(self,**kwargs):
                raise RuntimeError('synthetic private error not to leak')
        page=SimpleNamespace(url='https://ai-browser-vault.floot.app/browser-check',
                             context=Context())
        result=await synthetic_fixture_page_context_evidence(page)
        self.assertEqual(result,{'status':'readback_unavailable'})
        self.assertNotIn('private',str(result))


if __name__=='__main__':
    unittest.main(verbosity=2)

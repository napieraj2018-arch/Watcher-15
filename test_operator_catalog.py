"""Offline tests: no cookies, real logins, provider, Google API or browser calls."""
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import operator_catalog as oc


class FakeMCP:
    def __init__(self):
        self._tool_manager=SimpleNamespace(_tools={
            "browser_start":SimpleNamespace(fn=lambda **kw: "never_started")
        })

    def tool(self):
        def decorate(fn):
            if fn.__name__ in self._tool_manager._tools:
                raise ValueError("tool conflict")
            self._tool_manager._tools[fn.__name__] = SimpleNamespace(fn=fn)
            return fn
        return decorate


class OperatorCatalogTests(unittest.TestCase):
    def setUp(self):
        self.obj=oc.load_manifest("anita_reviews_v1")

    def raw(self,obj):
        return json.dumps(obj,ensure_ascii=False).encode("utf-8")

    def test_loaded_workflow_is_complete_and_public_only(self):
        w=self.obj
        self.assertEqual(w["schema_version"],1)
        self.assertEqual(w["workflow_id"],"anita_reviews_v1")
        self.assertEqual(w["expected_sources"]["instagram"]["expected_slides"],8)
        self.assertEqual(w["expected_sources"]["google_business"]["expected_reviews"],20)
        self.assertEqual(len(w["steps"]),5)
        self.assertTrue(w["no_reviews_embedded"])
        self.assertTrue(w["constraints"]["read_only_until_approval"])
        self.assertTrue(w["constraints"]["no_instagram_posts"])

    def test_other_workflow_names_are_rejected(self):
        for name in ("../secrets", "/tmp/config", "", None,"weterynarz"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(oc.CatalogError,"WORKFLOW_NOT_FOUND"):
                    oc.load_manifest(name)

    def test_do_not_accept_rogue_instagram_url(self):
        for invalid in [
            "http://www.instagram.com/stories/highlights/18102998546608585/",
            "https://www.instagram.com.evil.test/stories/highlights/18102998546608585/",
            "https://www.instagram.com/stories/highlights/18102998546608585/?token=should-not-appear",
            "https://someone@www.instagram.com/stories/highlights/18102998546608585/",
            "https://www.instagram.com/stories/highlights/../../evil/",
        ]:
            m=deepcopy(self.obj)
            m["expected_sources"]["instagram"]["highlight_url"]=invalid
            with self.subTest(invalid=invalid),self.assertRaisesRegex(
                    oc.CatalogError, "SOURCE_CONTRACT_FAILED"):
                oc.parse_manifest(self.raw(m),"anita_reviews_v1")

    def test_mismatched_business_cannot_be_substituted(self):
        m=deepcopy(self.obj)
        m["expected_sources"]["google_business"]["location_id"]="locations/999999"
        with self.assertRaisesRegex(oc.CatalogError,"SOURCE_CONTRACT_FAILED"):
            oc.parse_manifest(self.raw(m),"anita_reviews_v1")

    def test_missing_pub_guard_denies_manifest(self):
        m=deepcopy(self.obj)
        m["constraints"]["no_instagram_posts"]=False
        with self.assertRaisesRegex(oc.CatalogError,"APPROVAL_GUARDS_MISSING"):
            oc.parse_manifest(self.raw(m),"anita_reviews_v1")

    def test_untrusted_private_field_denied(self):
        for field in ("password","secret","cookie","access_token","authorization"):
            m=deepcopy(self.obj)
            m[field]="anything"
            with self.subTest(field=field),self.assertRaisesRegex(
                oc.CatalogError, "PRIVATE_FIELD_FORBIDDEN"
            ):
                oc.parse_manifest(self.raw(m),"anita_reviews_v1")

    def test_private_data_required_but_not_in_manifest(self):
        w=oc.describe_workflow("anita_reviews_v1")
        self.assertFalse(w["autonomous_execution_ready"])
        self.assertFalse(w["publish_allowed"])
        self.assertIsNone(w["session_authenticated"])
        self.assertEqual(w["private_checkpoint"]["configured"],False)
        self.assertNotIn("private_google_sheet_id",json.dumps(w).lower())

    def test_read_only_tools_register_after_existing_browser_catalog(self):
        mcp=FakeMCP()
        browser_tool=mcp._tool_manager._tools["browser_start"]
        namespace={"mcp":mcp,"manager":object()}
        self.assertEqual(oc.install(namespace),3)
        self.assertEqual(oc.install(namespace),0)
        self.assertIs(mcp._tool_manager._tools["browser_start"],browser_tool)
        tools=mcp._tool_manager._tools
        self.assertEqual(set(tools),{
            "browser_start","aib_workflow_list","aib_workflow_describe",
            "aib_route_operation"
        })
        desc=tools["aib_workflow_describe"].fn("anita_reviews_v1")
        self.assertFalse(desc["publish_allowed"])
        self.assertIn("highlight_url",desc["sources"]["instagram"])
        self.assertEqual(len(tools["aib_workflow_list"].fn()["workflows"]),1)
        route=tools["aib_route_operation"].fn("instagram","reel","anita")
        self.assertEqual(route["action"],"create_video_post")
        self.assertFalse(route["published"])
        self.assertEqual(route["account_authenticated"],"not_checked")
        self.assertEqual(tools["aib_workflow_describe"].fn("../../env")["error"],
                         "CATALOG_WORKFLOW_NOT_FOUND")

    def test_missing_mcp_fails_without_modification(self):
        ns={}
        with self.assertRaisesRegex(oc.CatalogError,"MCP_INCOMPATIBLE"):
            oc.install(ns)
        self.assertNotIn("_AIB_OPERATOR_CATALOG_READY",ns)

    def test_conflicting_registry_rejects_install(self):
        mcp=FakeMCP()
        mcp._tool_manager._tools["aib_workflow_list"]=object()
        with self.assertRaisesRegex(oc.CatalogError,"TOOL_CONFLICT"):
            oc.install({"mcp":mcp})

    def test_truncated_or_invalid_yaml_json_rejected(self):
        for value in (b"",b"[]",b"{",b"\xff",b" "*65537):
            with self.subTest(length=len(value)),self.assertRaises(oc.CatalogError):
                oc.parse_manifest(value,"anita_reviews_v1")


if __name__=="__main__":
    unittest.main(verbosity=2)

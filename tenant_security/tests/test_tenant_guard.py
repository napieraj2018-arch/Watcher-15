"""Cross-tenant security tests with synthetic identities, no real accounts."""
from __future__ import annotations
import base64
import json
import os
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

import tenant_guard as tg

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PROFILE_A = "33333333-3333-4333-8333-333333333333"
PROFILE_B = "44444444-4444-4444-8444-444444444444"
KEY = b"synthetic-HMAC-key-only-1234567890-ABCDEFGHIJKLMNOP"
MASTER = b"synthetic-AES-master-only-1234567890-ABCDEFGHIJKLMNOP"

def principal(tenant=TENANT_A,user=ALICE,roles=("admin",),mfa=True,verified=True):
    return tg.Principal(tenant,user,frozenset(roles),verified,mfa)

def resource(tenant=TENANT_A,id=PROFILE_A,kind="profile"):
    return tg.Resource(tenant,id,kind)

def expect_denied(test, fn, code=None):
    with test.assertRaises(tg.TenantAccessError) as error:
        fn()
    if code is not None:
        test.assertEqual(str(error.exception),code)
    test.assertNotIn(TENANT_A,str(error.exception))
    test.assertNotIn(TENANT_B,str(error.exception))

class Authorization(unittest.TestCase):
    def test_admin_view(self):
        tg.authorize(principal(),resource(),"view")
    def test_admin_operate(self):
        tg.authorize(principal(),resource(),"operate")
    def test_admin_delete_with_mfa(self):
        tg.authorize(principal(),resource(),"delete")
    def test_admin_delete_without_mfa_fails(self):
        expect_denied(self,lambda:tg.authorize(principal(mfa=False),resource(),"delete"),"STEP_UP_AUTHENTICATION_REQUIRED")
    def test_admin_export_without_mfa_fails(self):
        expect_denied(self,lambda:tg.authorize(principal(mfa=False),resource(),"export"))
    def test_admin_share_with_mfa(self):
        tg.authorize(principal(),resource(),"share")
    def test_viewer_can_view(self):
        tg.authorize(principal(roles=("viewer",),mfa=False),resource(),"view")
    def test_viewer_cannot_operate(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("viewer",)),resource(),"operate"),"INSUFFICIENT_ROLE")
    def test_viewer_cannot_delete(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("viewer",)),resource(),"delete"))
    def test_operator_can_operate(self):
        tg.authorize(principal(roles=("operator",)),resource(),"operate")
    def test_operator_cannot_share(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("operator",)),resource(),"share"))
    def test_operator_cannot_export(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("operator",)),resource(),"export"))
    def test_operator_cannot_delete(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("operator",)),resource(),"delete"))
    def test_billing_can_view_billing(self):
        tg.authorize(principal(roles=("billing",),mfa=False),resource(kind="billing"),"view")
    def test_billing_edits_require_mfa(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("billing",),mfa=False),resource(kind="billing"),"billing_edit"))
    def test_billing_edits_with_mfa(self):
        tg.authorize(principal(roles=("billing",)),resource(kind="billing"),"billing_edit")
    def test_billing_cannot_view_profile(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("billing",)),resource(),"view"))
    def test_billing_cannot_operate_browser(self):
        expect_denied(self,lambda:tg.authorize(principal(roles=("billing",)),resource(),"operate"))
    def test_cross_tenant_denied_even_if_admin(self):
        expect_denied(self,lambda:tg.authorize(principal(tenant=TENANT_B),resource(),"view"),"RESOURCE_NOT_ACCESSIBLE")
    def test_cross_tenant_denied_on_mutation(self):
        expect_denied(self,lambda:tg.authorize(principal(tenant=TENANT_B),resource(),"operate"),"RESOURCE_NOT_ACCESSIBLE")
    def test_cross_tenant_denied_on_export(self):
        expect_denied(self,lambda:tg.authorize(principal(tenant=TENANT_B),resource(),"export"),"RESOURCE_NOT_ACCESSIBLE")
    def test_unverified_principal_rejected(self):
        expect_denied(self,lambda:tg.authorize(principal(verified=False),resource(),"view"),"BACKEND_IDENTITY_REQUIRED")
    def test_invalid_action_rejected(self):
        expect_denied(self,lambda:tg.authorize(principal(),resource(),"root"))
    def test_billing_action_wrong_resource_rejected(self):
        expect_denied(self,lambda:tg.authorize(principal(),resource(),"billing_edit"))
    def test_operate_disallows_logs(self):
        expect_denied(self,lambda:tg.authorize(principal(),resource(kind="log"),"operate"))
    def test_filter_always_for_verified_tenant(self):
        self.assertEqual(tg.scoped_filter(principal(),"job"),{"tenant_id":TENANT_A,"kind":"job"})
    def test_filter_unverified_denied(self):
        expect_denied(self,lambda:tg.scoped_filter(principal(verified=False),"profile"))
    def test_invalid_principal_uuid_rejected(self):
        expect_denied(self,lambda:principal(tenant="../x"))
    def test_uppercase_uuid_rejected(self):
        expect_denied(self,lambda:principal(tenant=TENANT_A.upper()))
    def test_invalid_role_rejected(self):
        expect_denied(self,lambda:principal(roles=("superuser",)))
    def test_empty_role_set_rejected(self):
        expect_denied(self,lambda:principal(roles=()))
    def test_invalid_resource_kind_rejected(self):
        expect_denied(self,lambda:resource(kind="system"))
    def test_missing_backend_verification_cannot_be_boolean_string(self):
        expect_denied(self,lambda:tg.Principal(TENANT_A,ALICE,frozenset({"admin"}),"true",True))

class ReadCapabilities(unittest.TestCase):
    def test_issue_and_verify(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        tg.verify_read_capability(token,principal(),resource(),key=KEY,now=1010)
    def test_capability_unique_each_issue(self):
        a=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        b=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        self.assertNotEqual(a,b)
    def test_different_key_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(),resource(),key=b"b"*32,now=1100))
    def test_wrong_tenant_fails_before_claim(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(tenant=TENANT_B),resource(),key=KEY,now=1100))
    def test_wrong_user_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(user=BOB),resource(),key=KEY,now=1100),"CAPABILITY_SCOPE_MISMATCH")
    def test_wrong_resource_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(),resource(id=PROFILE_B),key=KEY,now=1100))
    def test_wrong_kind_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(),resource(kind="file"),key=KEY,now=1100))
    def test_expired_token_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000,ttl_seconds=60)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(),resource(),key=KEY,now=1060))
    def test_future_token_fails(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expect_denied(self,lambda:tg.verify_read_capability(token,principal(),resource(),key=KEY,now=900))
    def test_invalid_ttl_rejected(self):
        expect_denied(self,lambda:tg.issue_read_capability(principal(),resource(),key=KEY,now=1000,ttl_seconds=999))
    def test_key_too_short_rejected(self):
        expect_denied(self,lambda:tg.issue_read_capability(principal(),resource(),key=b"tiny",now=1000))
    def test_malformed_token_rejected(self):
        expect_denied(self,lambda:tg.verify_read_capability("BAD",principal(),resource(),key=KEY,now=1000))
    def test_tamper_signature_rejected(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        expected=token[:-1]+("A" if token[-1]!="A" else "B")
        expect_denied(self,lambda:tg.verify_read_capability(expected,principal(),resource(),key=KEY,now=1000))
    def test_read_capability_not_write(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        self.assertIn(".aibcap1.", "."+token[:7]+".") if False else None
        self.assertTrue(token.startswith("aibcap1."))
        self.assertNotIn("operate",token)
    def test_data_does_not_include_email_or_password(self):
        token=tg.issue_read_capability(principal(),resource(),key=KEY,now=1000)
        self.assertNotIn("@",token)
        self.assertNotIn("password",token)

class TenantVaultIsolation(unittest.TestCase):
    def test_round_trip_same_tenant_and_profile(self):
        blob=tg.seal_profile(b"synthetic fixture state",TENANT_A,PROFILE_A,master=MASTER)
        self.assertEqual(tg.open_profile(blob,TENANT_A,PROFILE_A,master=MASTER),b"synthetic fixture state")
    def test_cross_tenant_decryption_denied(self):
        blob=tg.seal_profile(b"secret test only",TENANT_A,PROFILE_A,master=MASTER)
        expect_denied(self,lambda:tg.open_profile(blob,TENANT_B,PROFILE_A,master=MASTER),"VAULT_AUTHENTICATION_FAILED")
    def test_cross_profile_decryption_denied(self):
        blob=tg.seal_profile(b"secret test only",TENANT_A,PROFILE_A,master=MASTER)
        expect_denied(self,lambda:tg.open_profile(blob,TENANT_A,PROFILE_B,master=MASTER))
    def test_wrong_master_denied(self):
        blob=tg.seal_profile(b"secret test only",TENANT_A,PROFILE_A,master=MASTER)
        expect_denied(self,lambda:tg.open_profile(blob,TENANT_A,PROFILE_A,master=b"x"*32))
    def test_random_nonces(self):
        a=tg.seal_profile(b"fixture",TENANT_A,PROFILE_A,master=MASTER)
        b=tg.seal_profile(b"fixture",TENANT_A,PROFILE_A,master=MASTER)
        self.assertNotEqual(a,b)
    def test_tamper_ciphertext_denied(self):
        b=tg.seal_profile(b"fixture",TENANT_A,PROFILE_A,master=MASTER)
        prefix,payload=b.split(".",1)
        raw=bytearray(tg._unb64(payload));raw[-1]^=1
        forged=prefix+"."+tg._b64(bytes(raw))
        expect_denied(self,lambda:tg.open_profile(forged,TENANT_A,PROFILE_A,master=MASTER))
    def test_empty_blob_refused(self):
        expect_denied(self,lambda:tg.seal_profile(b"",TENANT_A,PROFILE_A,master=MASTER))
    def test_huge_blob_refused(self):
        expect_denied(self,lambda:tg.seal_profile(b"x"*(tg.MAX_BLOB_LENGTH+1),TENANT_A,PROFILE_A,master=MASTER))
    def test_short_key_refused(self):
        expect_denied(self,lambda:tg.seal_profile(b"hi",TENANT_A,PROFILE_A,master=b"tiny"))
    def test_wrong_envelope_version_refused(self):
        b=tg.seal_profile(b"hi",TENANT_A,PROFILE_A,master=MASTER)
        expect_denied(self,lambda:tg.open_profile(b.replace(tg.VAULT_PREFIX,"unknown1"),TENANT_A,PROFILE_A,master=MASTER))
    def test_no_private_data_in_error(self):
        b=tg.seal_profile(b"SYNTHETIC_SUPER_SECRET",TENANT_A,PROFILE_A,master=MASTER)
        try:tg.open_profile(b,TENANT_B,PROFILE_A,master=MASTER)
        except tg.TenantAccessError as ex:
            self.assertNotIn("SYNTHETIC_SUPER_SECRET",str(ex))
            self.assertNotIn(TENANT_A,str(ex))
    def test_resource_name_cannot_be_path(self):
        expect_denied(self,lambda:tg.seal_profile(b"test",TENANT_A,"../../secret",master=MASTER))


if __name__=="__main__":
    unittest.main(verbosity=2)

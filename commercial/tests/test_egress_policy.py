"""Offline SSRF/navigation tests. Resolver is synthetic; no DNS or network."""
from __future__ import annotations
import copy
import json
import unittest

from commercial.egress_policy import (
    Policy, EgressBlocked, PinnedPermit, authorize, authorize_redirect,
    canonical_target, fqdn, public_ip, verify_transport_peer,
)

CLOCK=lambda:1000.0
A=Policy("tenant-A",frozenset({"example.com","www.example.com","cloudflare.com"}))
B=Policy("tenant-B",frozenset({"example.com","www.example.com"}))
GOOD={"example.com":["1.1.1.1","2606:4700:4700::1111"],
      "www.example.com":["1.0.0.1"],"cloudflare.com":["1.1.1.1"]}

def resolver(host):
    return list(GOOD[host])

def pin(policy=A,url="https://example.com/path?never-log=this-secret"):
    return authorize(policy,url,resolver,clock=CLOCK)

class PolicyChecks(unittest.TestCase):
    def test_valid_and_tenant_bounded(self):
        p=pin()
        self.assertEqual(p.tenant_id,"tenant-A")
        self.assertEqual(p.hostname,"example.com")
        self.assertEqual(p.addresses,frozenset({"1.1.1.1","2606:4700:4700::1111"}))
        self.assertNotIn("never-log",repr(p))
        self.assertNotIn("1.1.1.1",repr(p))

    def test_peer_pinning_tls(self):
        self.assertTrue(verify_transport_peer(
            pin(),tenant_id="tenant-A",peer_address="1.1.1.1",
            tls_hostname="example.com",tls_cert_verified=True,clock=CLOCK))

    def test_ipv6_global_peer(self):
        self.assertTrue(verify_transport_peer(
            pin(),tenant_id="tenant-A",peer_address="2606:4700:4700::1111",
            tls_hostname="example.com",tls_cert_verified=True,clock=CLOCK))

    def test_wrong_tenant_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"CROSS_TENANT_PERMIT"):
            verify_transport_peer(pin(),tenant_id="tenant-B",peer_address="1.1.1.1",
                                  tls_hostname="example.com",tls_cert_verified=True,clock=CLOCK)

    def test_wrong_tls_identity_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"TLS_IDENTITY_NOT_VERIFIED"):
            verify_transport_peer(pin(),tenant_id="tenant-A",peer_address="1.1.1.1",
                                  tls_hostname="other.example.com",tls_cert_verified=True,clock=CLOCK)

    def test_unverified_tls_certificate_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"TLS_IDENTITY_NOT_VERIFIED"):
            verify_transport_peer(pin(),tenant_id="tenant-A",peer_address="1.1.1.1",
                                  tls_hostname="example.com",tls_cert_verified=False,clock=CLOCK)

    def test_dns_rebind_peer_not_in_pins_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"DNS_REBIND_OR_PEER_MISMATCH"):
            verify_transport_peer(pin(),tenant_id="tenant-A",peer_address="8.8.8.8",
                                  tls_hostname="example.com",tls_cert_verified=True,clock=CLOCK)

    def test_expired_pin_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"PIN_EXPIRED"):
            verify_transport_peer(pin(),tenant_id="tenant-A",peer_address="1.1.1.1",
                                  tls_hostname="example.com",tls_cert_verified=True,clock=lambda:99999.0)

    def test_unapproved_host_rejected_even_with_public_dns(self):
        with self.assertRaisesRegex(EgressBlocked,"HOST_NOT_ALLOWED"):
            authorize(A,"https://evil.example.com/anything",lambda h:["1.1.1.1"],clock=CLOCK)

    def test_hostname_suffix_trick_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"HOST_NOT_ALLOWED"):
            authorize(A,"https://example.com.evil.test/anything",lambda h:["1.1.1.1"],clock=CLOCK)

    def test_internal_hosts_cannot_be_allowlisted(self):
        for host in ("localhost","localhost.local","metadata.internal","evil.invalid",
                     "metrics.local","foo.test","home.home.arpa"):
            with self.subTest(host=host),self.assertRaises(EgressBlocked):
                Policy("tenant-A",frozenset({host}))

    def test_private_dns_addresses_denied(self):
        for address in ("127.0.0.1","10.0.0.8","172.16.0.1","192.168.10.2",
                        "169.254.169.254","100.64.0.1","0.0.0.0","224.0.0.1",
                        "::1","fc00::1","fe80::1","::ffff:127.0.0.1",
                        "2001:db8::1","255.255.255.255"):
            with self.subTest(address=address),self.assertRaises(EgressBlocked):
                authorize(A,"https://example.com/",lambda _: [address],clock=CLOCK)

    def test_mixed_public_and_private_dns_fails_closed(self):
        with self.assertRaisesRegex(EgressBlocked,"DNS_NONPUBLIC_ADDRESS"):
            authorize(A,"https://example.com/",lambda _:["1.1.1.1","127.0.0.1"],clock=CLOCK)

    def test_no_dns_responses_denied(self):
        with self.assertRaisesRegex(EgressBlocked,"DNS_ANSWER_COUNT_INVALID"):
            authorize(A,"https://example.com/",lambda _:[],clock=CLOCK)

    def test_large_dns_response_denied(self):
        with self.assertRaisesRegex(EgressBlocked,"DNS_ANSWER_COUNT_INVALID"):
            authorize(A,"https://example.com/",lambda _:["1.1.1.1"]*17,clock=CLOCK)

    def test_resolver_exception_redacted(self):
        def broken(_):raise RuntimeError("SYNTHETIC_INTERNAL_RESOLVER_TOKEN")
        with self.assertRaisesRegex(EgressBlocked,"DNS_RESOLUTION_FAILED") as err:
            authorize(A,"https://example.com/",broken,clock=CLOCK)
        self.assertNotIn("TOKEN",str(err.exception))

    def test_url_schemes_and_userinfo_denied(self):
        for target in ("http://example.com/","ftp://example.com/","file:///etc/passwd",
                       "javascript:alert(1)","https://user:pass@example.com/",
                       "https://@example.com/","https://example.com:8443/",
                       "https://example.com\\@evil.test/"):
            with self.subTest(target=target),self.assertRaises(EgressBlocked):
                authorize(A,target,lambda _:["1.1.1.1"],clock=CLOCK)

    def test_direct_ip_host_rejected(self):
        for target in ("https://127.0.0.1/","https://8.8.8.8/",
                       "https://169.254.169.254/","https://[::1]/"):
            with self.subTest(target=target),self.assertRaises(EgressBlocked):
                authorize(Policy("tenant-A",frozenset({"example.com"})),target,
                          lambda _:["1.1.1.1"],clock=CLOCK)

    def test_nonstandard_port_denied(self):
        for target in ("https://example.com:444/","https://example.com:65535/"):
            with self.subTest(target=target),self.assertRaises(EgressBlocked):
                authorize(A,target,lambda _:["1.1.1.1"],clock=CLOCK)

    def test_url_spaces_crlf_denied(self):
        for target in ("https://example.com/hello world",
                       "https://example.com/path\nX-Forwarded-Host:evil.test",
                       "https://example.com/\\evil"):
            with self.subTest(target=target),self.assertRaises(EgressBlocked):
                authorize(A,target,resolver,clock=CLOCK)

    def test_expired_redirect_denied(self):
        with self.assertRaisesRegex(EgressBlocked,"PREVIOUS_PIN_EXPIRED"):
            authorize_redirect(A,pin(),"https://example.com/next",resolver,clock=lambda:99999.0)

    def test_cross_origin_redirect_requires_approval(self):
        with self.assertRaisesRegex(EgressBlocked,"CROSS_ORIGIN_REDIRECT_REQUIRES_APPROVAL"):
            authorize_redirect(A,pin(),"https://www.example.com/next",resolver,clock=CLOCK)

    def test_cross_origin_redirect_with_approval_and_allowed_host(self):
        p=authorize_redirect(A,pin(),"https://www.example.com/next",resolver,
                             allow_cross_origin=True,clock=CLOCK)
        self.assertTrue(p.cross_origin_approved)
        self.assertEqual(p.hostname,"www.example.com")

    def test_cross_tenant_redirect_rejected(self):
        with self.assertRaisesRegex(EgressBlocked,"CROSS_TENANT_REDIRECT"):
            authorize_redirect(B,pin(),"https://example.com/",resolver,clock=CLOCK)

    def test_redirect_to_private_host_never_approved(self):
        with self.assertRaises(EgressBlocked):
            authorize_redirect(A,pin(),"https://127.0.0.1/",lambda _:["127.0.0.1"],
                               allow_cross_origin=True,clock=CLOCK)

    def test_wrong_pin_ttl_fails(self):
        for value in (-1,0,31,False,1.5):
            with self.subTest(value=value),self.assertRaises(EgressBlocked):
                authorize(A,"https://example.com/",resolver,clock=CLOCK,lifetime_seconds=value)

    def test_clock_nan_fails(self):
        with self.assertRaisesRegex(EgressBlocked,"INVALID_CLOCK"):
            authorize(A,"https://example.com/",resolver,clock=lambda:float("nan"))

    def test_policy_cannot_accept_unbounded_hosts(self):
        hosts=frozenset(f"a{i}.example.com" for i in range(101))
        with self.assertRaisesRegex(EgressBlocked,"POLICY_HOSTS_INVALID"):
            Policy("tenant-A",hosts)

    def test_policy_hosts_must_be_lowercase(self):
        with self.assertRaisesRegex(EgressBlocked,"POLICY_HOSTS_NONCANONICAL"):
            Policy("tenant-A",frozenset({"Example.com"}))

    def test_query_secrets_never_in_permit_repr(self):
        token="FAKE_ONLY_DO_NOT_LOG"
        p=authorize(A,"https://example.com/?token="+token,resolver,clock=CLOCK)
        self.assertNotIn(token,repr(p))
        self.assertNotIn(token,json.dumps({"tenant":p.tenant_id,"host":p.hostname}))

    def test_no_shared_state_mutation(self):
        source=copy.deepcopy(GOOD)
        p=authorize(A,"https://example.com/",resolver,clock=CLOCK)
        self.assertEqual(source,GOOD)
        self.assertIsInstance(p.addresses,frozenset)

    def test_bad_host_config_rejected(self):
        for host in ("*.example.com","example..com","-a.com","a-.com",
                     "a/com","EXAMPLE.COM","127.0.0.1"):
            with self.subTest(host=host),self.assertRaises(EgressBlocked):
                Policy("tenant-A",frozenset({host}))

    def test_dns_response_not_list_rejected(self):
        for output in ({"ip":"1.1.1.1"},"1.1.1.1",None):
            with self.subTest(output=output),self.assertRaises(EgressBlocked):
                authorize(A,"https://example.com/",lambda _:output,clock=CLOCK)

if __name__=="__main__":
    unittest.main(verbosity=2)

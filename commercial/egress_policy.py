"""AI Browser tenant-scoped outbound navigation policy — NOT deployed.

An application-side allowlist does not, by itself, stop SSRF inside a remote
browser provider. The transport MUST pin the actual TCP destination to an
authorized, globally routable IP, verify the HTTPS certificate against the
approved hostname, and repeat this process on every redirect/network request.

This module is deliberately pure and deterministic: the resolver is injected,
so unit tests cannot contact the network or user accounts.
"""
from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Callable, Sequence
from urllib.parse import urlsplit

MAX_URL_CHARS = 4096
MAX_ANSWERS = 16
MAX_PIN_SECONDS = 30
HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,79}$")

class EgressBlocked(ValueError):
    """Fixed error code; intentionally never echoes URLs or DNS answers."""

def fqdn(host: object) -> str:
    if not isinstance(host, str) or not host or len(host) > 253:
        raise EgressBlocked("HOST_INVALID")
    if not host.isascii() or host.endswith(".") or "%" in host:
        raise EgressBlocked("HOST_INVALID")
    host = host.lower()
    labels = host.split(".")
    if len(labels) < 2 or any(not HOST_LABEL.fullmatch(label) for label in labels):
        raise EgressBlocked("HOST_INVALID")
    if host.endswith((".local", ".localhost", ".internal", ".invalid", ".test", ".home.arpa")):
        raise EgressBlocked("HOST_INTERNAL_OR_SYNTHETIC")
    return host

def canonical_target(url: object) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= MAX_URL_CHARS:
        raise EgressBlocked("URL_INVALID")
    if re.search(r"[\x00-\x20\x7f\\]", url):
        raise EgressBlocked("URL_CONTROL_CHARACTER")
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise EgressBlocked("HTTPS_REQUIRED")
        if parsed.port not in (None, 443):
            raise EgressBlocked("NONSTANDARD_PORT")
        if not parsed.hostname:
            raise EgressBlocked("HOST_INVALID")
        return fqdn(parsed.hostname)
    except (TypeError, ValueError):
        raise EgressBlocked("URL_INVALID") from None

def public_ip(ip_text: object) -> str:
    if not isinstance(ip_text, str) or not ip_text or len(ip_text) > 64:
        raise EgressBlocked("DNS_ADDRESS_INVALID")
    try:
        parsed = ipaddress.ip_address(ip_text)
    except ValueError:
        raise EgressBlocked("DNS_ADDRESS_INVALID") from None
    if (not parsed.is_global or parsed.is_multicast or parsed.is_reserved
            or parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified
            or getattr(parsed, "ipv4_mapped", None) is not None):
        raise EgressBlocked("DNS_NONPUBLIC_ADDRESS")
    return parsed.compressed

@dataclass(frozen=True)
class Policy:
    tenant_id: str
    allowed_hosts: frozenset[str]

    def __post_init__(self) -> None:
        if (not isinstance(self.tenant_id, str)
                or not IDENTIFIER.fullmatch(self.tenant_id)):
            raise EgressBlocked("TENANT_ID_INVALID")
        if (not isinstance(self.allowed_hosts, frozenset)
                or not 1 <= len(self.allowed_hosts) <= 100):
            raise EgressBlocked("POLICY_HOSTS_INVALID")
        for host in self.allowed_hosts:
            if fqdn(host) != host:
                raise EgressBlocked("POLICY_HOSTS_NONCANONICAL")

@dataclass(frozen=True)
class PinnedPermit:
    tenant_id: str
    hostname: str
    addresses: frozenset[str]
    expires_at: float
    cross_origin_approved: bool = False

    def __repr__(self) -> str:
        # Avoid DNS answers and target details in ordinary logs.
        return "<PinnedPermit tenant-scoped HTTPS authorization>"

def authorize(
    policy: Policy, target_url: str, resolver: Callable[[str], Sequence[str]],
    *, clock: Callable[[], float] = time.monotonic, lifetime_seconds: int = 15,
) -> PinnedPermit:
    if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= MAX_PIN_SECONDS:
        raise EgressBlocked("PIN_LIFETIME_INVALID")
    host = canonical_target(target_url)
    if host not in policy.allowed_hosts:
        raise EgressBlocked("HOST_NOT_ALLOWED")
    try:
        results = resolver(host)
    except Exception:
        raise EgressBlocked("DNS_RESOLUTION_FAILED") from None
    if (not isinstance(results, (tuple, list))
            or not 1 <= len(results) <= MAX_ANSWERS):
        raise EgressBlocked("DNS_ANSWER_COUNT_INVALID")
    # Reject ANY private answer, not only the address selected first.
    public_addresses = frozenset(public_ip(v) for v in results)
    if not public_addresses:
        raise EgressBlocked("DNS_NO_PUBLIC_ANSWERS")
    now = clock()
    if not isinstance(now, (int, float)) or not (0 <= now < float("inf")):
        raise EgressBlocked("INVALID_CLOCK")
    return PinnedPermit(policy.tenant_id, host, public_addresses, now + lifetime_seconds)

def authorize_redirect(
    policy: Policy, previous: PinnedPermit, destination: str,
    resolver: Callable[[str], Sequence[str]],
    *, allow_cross_origin: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> PinnedPermit:
    if not isinstance(previous, PinnedPermit) or previous.tenant_id != policy.tenant_id:
        raise EgressBlocked("CROSS_TENANT_REDIRECT")
    next_host = canonical_target(destination)
    if next_host != previous.hostname and allow_cross_origin is not True:
        raise EgressBlocked("CROSS_ORIGIN_REDIRECT_REQUIRES_APPROVAL")
    if clock() >= previous.expires_at:
        raise EgressBlocked("PREVIOUS_PIN_EXPIRED")
    pin = authorize(policy, destination, resolver, clock=clock)
    return PinnedPermit(pin.tenant_id, pin.hostname, pin.addresses, pin.expires_at,
                        cross_origin_approved=next_host != previous.hostname)

def verify_transport_peer(
    permit: PinnedPermit, *, tenant_id: str, peer_address: str,
    tls_hostname: str, tls_cert_verified: bool,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """The transport MUST call this after pinning TCP to peer_address.

    tls_cert_verified is an assertion from the trusted TLS socket, never a
    value supplied by webpage JavaScript or an untrusted agent.
    """
    if not isinstance(permit, PinnedPermit) or permit.tenant_id != tenant_id:
        raise EgressBlocked("CROSS_TENANT_PERMIT")
    if clock() >= permit.expires_at:
        raise EgressBlocked("PIN_EXPIRED")
    if tls_hostname != permit.hostname or tls_cert_verified is not True:
        raise EgressBlocked("TLS_IDENTITY_NOT_VERIFIED")
    if public_ip(peer_address) not in permit.addresses:
        raise EgressBlocked("DNS_REBIND_OR_PEER_MISMATCH")
    return True

"""Evidence-first release gate for selling AI Browser to external tenants.

Offline checklist validator only. This does NOT prove security or perform
production actions. A green unit-test run is not a sales release approval.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import json
import re
import sys
import argparse

REQUIRED = {
    "tenant_auth": "Each purchaser has authenticated, recoverable identity",
    "tenant_profile_isolation": "No tenant can list/load/modify another tenant's profiles",
    "session_owner_leases": "All MCP and mobile routes enforce per-task ownership",
    "mcp_scoped_credentials": "MCP auth uses scoped, rotatable non-URL credentials",
    "secrets_vault": "At-rest secrets are encrypted with verified import/revoke/rotate",
    "ssrf_egress": "Navigation and backend requests cannot reach private internal networks",
    "human_verification": "MFA/CAPTCHA pauses securely for human confirmation",
    "profile_coherent_restore": "Real session reopens with coherent cookie and web storage",
    "profile_deletion": "Delete propagates to native provider and every backup/version",
    "provider_retention_policy": "Provider retention expiry is monitored and mitigated",
    "backup_restore": "Encrypted backup/restore exercised and audited",
    "lease_crash_recovery": "Crash/timeout releases or quarantines leases without cross-user reuse",
    "log_sanitization": "Logs/recordings have redaction, retention and access controls",
    "per_tenant_quotas": "Concurrency, costs, rate limits and file sizes are enforced per tenant",
    "download_upload_isolation": "Malware/content-type/size and tenant path isolation are verified",
    "billing_idempotency": "Subscriptions, payment events and refunds are handled idempotently",
    "production_slo": "Paid-capacity hosting, observability and incident alerts are tested",
    "gdpr_deletion_export": "Data export/erasure + privacy notice and contractual DPA are complete",
    "mobile_accessibility": "Integrated iPhone UX meets accessibility and touch target criteria",
    "consent_action_audit": "Publishing/spend/settings require explicit auditable user scopes",
}
SEVERITY = {k: ("high" if k in {
    "provider_retention_policy","backup_restore","per_tenant_quotas","billing_idempotency",
    "production_slo","mobile_accessibility"
} else "critical") for k in REQUIRED}
STATUS = {"blocked", "unverified", "partial", "verified"}
HEX_SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_SIZE = 150000
MAX_EVIDENCE_AGE_DAYS = 30

class GateError(ValueError):
    """Static code only, without untrusted content or secrets."""

def parse_time(v):
    if not isinstance(v,str):
        raise GateError("INVALID_EVIDENCE_DATE")
    try:
        dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError:
        raise GateError("INVALID_EVIDENCE_DATE") from None
    if dt.tzinfo is None:
        raise GateError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)

def validate_attestation(item, now):
    if not isinstance(item,dict) or set(item)!={"kind","url","verified_at","artifact_sha256"}:
        raise GateError("INVALID_ATTESTATION_SHAPE")
    if item["kind"] not in {"automated","manual_review","contract"}:
        raise GateError("INVALID_ATTESTATION_KIND")
    url=item["url"]
    if not isinstance(url,str) or len(url)>1024:
        raise GateError("INVALID_ATTESTATION_URL")
    p=urlparse(url)
    if p.scheme!="https" or p.netloc not in {
        "github.com","docs.github.com","dashboard.render.com","support.steel.dev"
    } or p.username or p.password or p.query or p.fragment:
        raise GateError("ATTESTATION_URL_NOT_ALLOWED")
    if not isinstance(item["artifact_sha256"],str) or not HEX_SHA.fullmatch(item["artifact_sha256"]):
        raise GateError("INVALID_ATTESTATION_HASH")
    stamp=parse_time(item["verified_at"])
    if stamp>now+timedelta(minutes=5) or now-stamp>timedelta(days=MAX_EVIDENCE_AGE_DAYS):
        raise GateError("ATTESTATION_STALE_OR_FUTURE")

def evaluate(manifest:dict, now:datetime|None=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise GateError("NAIVE_CLOCK")
    if not isinstance(manifest,dict) or set(manifest)!={"schema_version","controls","note"}:
        raise GateError("INVALID_MANIFEST_FIELDS")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"]!=1:
        raise GateError("INVALID_SCHEMA")
    if not isinstance(manifest["note"],str) or len(manifest["note"])>1500:
        raise GateError("INVALID_NOTE")
    raw=manifest["controls"]
    if not isinstance(raw,list) or len(raw)!=len(REQUIRED):
        raise GateError("REQUIRED_CONTROLS_MISSING")
    seen=set()
    metrics={s:0 for s in STATUS}
    blockers=[]
    for control in raw:
        if not isinstance(control,dict) or set(control)!={"id","status","notes","attestations"}:
            raise GateError("INVALID_CONTROL_FIELDS")
        id=control["id"]
        if id not in REQUIRED or id in seen:
            raise GateError("CONTROL_ID_UNKNOWN_OR_DUPLICATE")
        seen.add(id)
        status=control["status"]
        if status not in STATUS:
            raise GateError("INVALID_CONTROL_STATUS")
        notes=control["notes"]
        if not isinstance(notes,str) or len(notes)>600:
            raise GateError("INVALID_CONTROL_NOTES")
        attestations=control["attestations"]
        if not isinstance(attestations,list) or len(attestations)>8:
            raise GateError("INVALID_ATTESTATIONS")
        for att in attestations:
            validate_attestation(att,now)
        # An assertion of being verified without recent evidence is no pass.
        if status=="verified" and not attestations:
            raise GateError("VERIFIED_WITHOUT_EVIDENCE")
        metrics[status]+=1
        if status!="verified":
            blockers.append({"id":id,"severity":SEVERITY[id],"status":status})
    if seen != set(REQUIRED):
        raise GateError("REQUIRED_CONTROLS_MISSING")
    blockers.sort(key=lambda b:(0 if b["severity"]=="critical" else 1,b["id"]))
    # Verified here only means the evidence MANIFEST is complete; independent
    # technical, legal and penetration-test acceptance is still required.
    return {
      "ready_for_independent_acceptance": len(blockers)==0,
      "commercial_launch_approved":False,
      "total_controls":len(REQUIRED),
      "status_counts":metrics,
      "blocking_controls":blockers,
      "statement":"Manifest check only; no security or legal approval implied.",
    }

def duplicate_key_guard(pairs):
    out={}
    for k,v in pairs:
        if k in out:
            raise GateError("DUPLICATE_JSON_KEY")
        out[k]=v
    return out

def load(path:Path):
    if path.stat().st_size>MAX_SIZE:
        raise GateError("MANIFEST_TOO_LARGE")
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=duplicate_key_guard,
                          parse_constant=lambda v: (_ for _ in ()).throw(GateError("INVALID_NUMBER")))
    except (UnicodeError,json.JSONDecodeError):
        raise GateError("INVALID_JSON") from None

def main(args=None):
    parser=argparse.ArgumentParser(description="Read-only AI Browser commercial release gate")
    parser.add_argument("manifest",type=Path)
    ns=parser.parse_args(args)
    try:
        report=evaluate(load(ns.manifest))
    except (GateError,OSError):
        print(json.dumps({"commercial_launch_approved":False,"error":"MANIFEST_INVALID"}))
        return 2
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["ready_for_independent_acceptance"] else 1

if __name__=="__main__":
    sys.exit(main())

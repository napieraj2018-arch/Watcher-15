"""Read-only autonomous workflow catalogue served by the existing AI Browser MCP.

This module DOES NOT access a browser, customer data or credentials. It
unifies versioned, privacy-safe operating procedures with MCP discovery.
True cross-conversation private checkpoint execution still needs a trusted,
tenant-authenticated database connector.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parent
FILES = {"anita_reviews_v1": "workflows/anita/reviews.yaml"}
MAX_MANIFEST_BYTES = 65_536
PRIVATE_KEYS = frozenset((
    "password", "passphrase", "secret", "access_token", "refresh_token",
    "cookie", "storage_state", "session_token", "bearer", "authorization"
))


class CatalogError(ValueError):
    """Fixed message only; never echo invalid manifest data."""


def _no_private_values(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if not isinstance(key, str):
                raise CatalogError("CATALOG_INVALID_FIELD")
            norm = key.lower().replace("-", "_")
            if norm in PRIVATE_KEYS:
                raise CatalogError("CATALOG_PRIVATE_FIELD_FORBIDDEN")
            _no_private_values(val)
    elif isinstance(obj, list):
        for val in obj:
            _no_private_values(val)


def _safe_highlight_url(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > 250:
        return False
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.instagram.com"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query and not parsed.fragment
        and re.fullmatch(r"/stories/highlights/[0-9]{12,30}/", parsed.path) is not None
    )


def parse_manifest(raw: bytes, expected_id: str) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_MANIFEST_BYTES:
        raise CatalogError("CATALOG_INVALID_SIZE")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise CatalogError("CATALOG_INVALID_JSON_YAML") from None
    # JSON is a compatible subset of YAML 1.2 and needs no extra YAML parser.
    if not isinstance(obj, dict):
        raise CatalogError("CATALOG_INVALID_STRUCTURE")
    _no_private_values(obj)
    if (obj.get("schema_version") != SCHEMA_VERSION
        or obj.get("workflow_id") != expected_id
        or not isinstance(obj.get("title"), str)
        or not isinstance(obj.get("tenant_scope"), str)):
        raise CatalogError("CATALOG_INVALID_SCHEMA")
    sources = obj.get("expected_sources", {})
    ig = sources.get("instagram", {}) if isinstance(sources, dict) else {}
    google = sources.get("google_business", {}) if isinstance(sources, dict) else {}
    if (not _safe_highlight_url(ig.get("highlight_url"))
        or ig.get("profile") != "Meta - Anita"
        or ig.get("instagram_business_id") != "17841400064953151"
        or ig.get("expected_slides") != 8
        or google.get("location_id") != "locations/17588627068282939119"
        or google.get("expected_reviews") != 20):
        raise CatalogError("CATALOG_SOURCE_CONTRACT_FAILED")
    restrictions = obj.get("constraints", {})
    if (not isinstance(restrictions, dict)
        or restrictions.get("read_only_until_approval") is not True
        or restrictions.get("no_instagram_posts") is not True
        or restrictions.get("no_facebook_posts") is not True
        or restrictions.get("no_vet_brand_access") is not True
        or restrictions.get("require_eight_real_screenshots") is not True):
        raise CatalogError("CATALOG_APPROVAL_GUARDS_MISSING")
    steps = obj.get("steps")
    if (not isinstance(steps, list) or len(steps) != 5
        or not all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in steps)
        or len({x["id"] for x in steps}) != 5):
        raise CatalogError("CATALOG_STEPS_INCOMPLETE")
    private = obj.get("trusted_private_memory", {})
    if (not isinstance(private, dict)
        or private.get("requires_authenticated_tenant") is not True
        or private.get("may_commit_private_content_to_repo") is not False
        or obj.get("no_reviews_embedded") is not True):
        raise CatalogError("CATALOG_PRIVACY_GUARDS_MISSING")
    return obj


def load_manifest(workflow_id: str) -> dict:
    if not isinstance(workflow_id, str) or workflow_id not in FILES:
        raise CatalogError("CATALOG_WORKFLOW_NOT_FOUND")
    file_path = (ROOT / FILES[workflow_id]).resolve()
    if not file_path.is_relative_to(ROOT):
        raise CatalogError("CATALOG_PATH_UNSAFE")
    try:
        blob = file_path.read_bytes()
    except OSError:
        raise CatalogError("CATALOG_MANIFEST_UNAVAILABLE") from None
    return parse_manifest(blob, workflow_id)


def list_workflows() -> dict:
    # List is public metadata; never enumerate private runs, usernames or
    # sessions from connected customers.
    items = []
    for workflow_id in sorted(FILES):
        item = load_manifest(workflow_id)
        items.append({"workflow_id":workflow_id, "title":item["title"],
                      "schema_version":item["schema_version"]})
    return {"workflows":items, "private_run_data_included":False}


def describe_workflow(workflow_id: str) -> dict:
    item = load_manifest(workflow_id)
    return {
        "workflow_id":item["workflow_id"],
        "title":item["title"],
        "tenant_scope":item["tenant_scope"],
        "sources":item["expected_sources"],
        "steps":item["steps"],
        "guards":item["constraints"],
        "private_checkpoint": {
            "configured":False,
            "reason":"TENANT_PRIVATE_BACKEND_NOT_ATTACHED_TO_MCP",
            "required":True
        },
        "session_authenticated":None,
        "autonomous_execution_ready":False,
        "publish_allowed":False
    }


def install(namespace: dict) -> int:
    """Register two SAFE introspection tools after ownership-guard preflight.

    The current MCP endpoint uses an owner bearer token, but there is no
    production tenant auth. Never expose customer state through these tools.
    """
    if namespace.get("_AIB_OPERATOR_CATALOG_READY") is True:
        return 0
    mcp = namespace.get("mcp")
    registry = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    if (mcp is None or not callable(getattr(mcp, "tool", None))
        or not isinstance(registry, dict)):
        raise CatalogError("CATALOG_MCP_INCOMPATIBLE")
    names = ("aib_workflow_list", "aib_workflow_describe")
    if any(name in registry for name in names):
        raise CatalogError("CATALOG_TOOL_CONFLICT")
    # Fail startup before registering any tools if the manifest is broken.
    list_workflows()

    def aib_workflow_list() -> dict:
        """List available safe, versioned AI Browser operating procedures."""
        return list_workflows()

    def aib_workflow_describe(workflow_id: str) -> dict:
        """Get a workflow's steps and sources, never private run data."""
        try:
            return describe_workflow(workflow_id)
        except CatalogError as exc:
            return {"error":str(exc), "private_run_data_included":False}

    mcp.tool()(aib_workflow_list)
    mcp.tool()(aib_workflow_describe)
    if not all(name in registry for name in names):
        raise CatalogError("CATALOG_REGISTRATION_FAILED")
    namespace["_AIB_OPERATOR_CATALOG_READY"] = True
    print("AI_BROWSER_OPERATOR_CATALOG_READY 2", flush=True)
    return 2

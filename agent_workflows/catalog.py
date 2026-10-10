"""Read-only, public workflow definitions. NO private user task results here.

workflows/anita/reviews.yaml is deliberately a JSON document (valid YAML 1.2)
to avoid adding a YAML parser to the production runtime. All actual IDs,
review authors, quotes, images, session data and progress must be obtained
from a separate, authenticated and tenant-isolated private store.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {"reviews.deduplicate.graphics": "workflows/anita/reviews.yaml"}
STEP_NAMES = frozenset({
    "verify_owner_and_account_identity",
    "read_all_highlight_images",
    "read_all_business_reviews",
    "normalize_and_find_similarities",
    "compare_against_private_used_reviews",
    "classify_used_unused_needs_verification",
    "render_only_verified_unused_reviews",
    "create_private_zip_for_approval",
})
TOP_LEVEL = frozenset({
    "schema_version", "workflow_id", "version", "status",
    "source_requirements", "steps", "private_bindings", "evidence", "safety",
})


class WorkflowCatalogError(ValueError):
    """Fixed non-sensitive error code for untrusted identifiers/catalog data."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise WorkflowCatalogError("WORKFLOW_DUPLICATE_KEY")
        result[name] = value
    return result


def load_workflow(workflow_id: str, *, root: Path | None = None) -> dict:
    if not isinstance(workflow_id, str) or workflow_id not in WORKFLOWS:
        raise WorkflowCatalogError("WORKFLOW_NOT_AVAILABLE")
    location = (root or ROOT) / WORKFLOWS[workflow_id]
    try:
        if location.is_symlink() or location.stat().st_size > 25000:
            raise WorkflowCatalogError("WORKFLOW_MANIFEST_UNSAFE")
        document = json.loads(location.read_text(encoding="utf-8"),
                              object_pairs_hook=_object_without_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise WorkflowCatalogError("WORKFLOW_MANIFEST_INVALID") from None
    if (not isinstance(document, dict)
        or set(document) != TOP_LEVEL
        or document.get("schema_version") != 1
        or document.get("workflow_id") != workflow_id
        or document.get("status") != "template_requires_private_tenant_binding"
        or not isinstance(document.get("version"), str)
        or len(document["version"]) > 32):
        raise WorkflowCatalogError("WORKFLOW_MANIFEST_INVALID")
    steps = document.get("steps")
    if (not isinstance(steps, list)
            or steps != list(dict.fromkeys(steps))
            or set(steps) != STEP_NAMES):
        raise WorkflowCatalogError("WORKFLOW_STEPS_INVALID")
    sources = document.get("source_requirements")
    if (not isinstance(sources, list) or len(sources) != 2
            or any(not isinstance(src, dict) or
                   set(src) != {"role", "media", "expected_count"} or
                   type(src["expected_count"]) is not int or
                   src["expected_count"] <= 0 for src in sources)):
        raise WorkflowCatalogError("WORKFLOW_SOURCES_INVALID")
    private = document.get("private_bindings")
    if (not isinstance(private, list) or len(private) < 3 or
            any(not isinstance(v, str) or
                not v.replace("_", "").isalnum() or len(v) > 70
                for v in private)):
        raise WorkflowCatalogError("WORKFLOW_BINDINGS_INVALID")
    guards = document.get("safety")
    if (not isinstance(guards, dict)
        or not guards
        or any(type(value) is not bool or value is not True
               for value in guards.values())):
        raise WorkflowCatalogError("WORKFLOW_SAFETY_INVALID")
    evidence = document.get("evidence")
    if (not isinstance(evidence, dict)
        or any(type(v) is not bool or v is not True
               for v in evidence.values())):
        raise WorkflowCatalogError("WORKFLOW_EVIDENCE_INVALID")

    # Public catalog cannot contain any private source or account binding.
    # No user-specific URLs, access keys, screenshots or author names.
    serialized = json.dumps(document, ensure_ascii=False).lower()
    for blocked in ("access_token", "refresh_token", "cookie_value",
                    "password_value", "secret_value", "session_id",
                    "private_key", "customer_id", "author_name", "https://",
                    "http://", "locations/", "instagram.com/"):
        if blocked in serialized:
            raise WorkflowCatalogError("WORKFLOW_PRIVATE_DATA_FORBIDDEN")
    return deepcopy(document)


def list_workflows(*, root: Path | None = None) -> dict:
    definitions = []
    for workflow_id in WORKFLOWS:
        item = load_workflow(workflow_id, root=root)
        definitions.append({
            "workflow_id": workflow_id,
            "version": item["version"],
            "state": item["status"],
            "requires_private_binding": True,
        })
    return {
        "workflows": definitions,
        "private_execution_history_available": False,
        "live_authentication_verified": False,
        "running_tasks_verified": False,
    }

"""Read-only reconciliation of durable WordPress write receipts.

This extension never sends WordPress POST requests. An uncertain operation is
completed only when the expected fields can be independently read back. The
existing authentication, lease, profile and human-handoff guards stay in force.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import time

from fastapi import HTTPException
import visual_runtime
import production_runtime as prod
import server

app = visual_runtime.app
_previous_action = server.workspace.action
_RECEIPT_FIELDS = {
    "ok", "verified", "target", "sha256", "operation_id", "task_id",
    "verification_basis", "external_write_replayed",
}
_MAX_BACKUP_BYTES = 50000


def operation_key(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        raise HTTPException(400, "Wymagany operation_id w obiekcie JSON.") from None
    if (not isinstance(value, dict) or set(value) != {"operation_id"}
            or not isinstance(value["operation_id"], str)
            or re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", value["operation_id"]) is None):
        raise HTTPException(400, "Nieprawidłowy operation_id.")
    operation = value["operation_id"]
    return operation, "wp-op-" + hashlib.sha256(operation.encode()).hexdigest()[:32]


def checked_state(record):
    state = record.get("checkpoint") if isinstance(record, dict) else None
    if (not isinstance(state, dict) or type(record.get("revision")) is not int
            or record["revision"] < 1 or state.get("account") != "edycjanapieraj"
            or re.fullmatch(r"[a-f0-9]{64}", str(state.get("request_hash", ""))) is None
            or state.get("phase") not in {"prepared", "submitted", "acknowledged", "verified"}):
        raise HTTPException(409, "Nierozpoznany zapis operacji. Nie zmieniono stanu.")
    return state


def safe_receipt(state, operation, task_id):
    receipt = state.get("receipt")
    if (not isinstance(receipt, dict) or receipt.get("operation_id") != operation
            or receipt.get("task_id") != task_id or receipt.get("verified") is not True
            or receipt.get("ok") is not True):
        raise HTTPException(409, "Nieprawidłowe potwierdzenie operacji.")
    return {k: v for k, v in receipt.items() if k in _RECEIPT_FIELDS}


async def read_desired(reference):
    """Read a bounded encrypted backup and verify every offset and the full hash."""
    try:
        chunks = reference["chunks"]
        size = reference["bytes"]
        digest = reference["sha256"]
        if (not isinstance(chunks, list) or not 1 <= len(chunks) <= 3
                or len(set(chunks)) != len(chunks) or type(size) is not int
                or not 1 <= size <= _MAX_BACKUP_BYTES
                or re.fullmatch(r"[a-f0-9]{64}", str(digest)) is None):
            raise ValueError()
        data = bytearray()
        for ident in chunks:
            if not isinstance(ident, str) or re.fullmatch(r"wp-b-[a-f0-9]{32}", ident) is None:
                raise ValueError()
            saved = await asyncio.to_thread(server.db_checkpoint, ident)
            block = saved["checkpoint"]
            if (block["encoding"] != "base64-json-chunk"
                    or type(block["offset"]) is not int or block["offset"] != len(data)
                    or block["sha256"] != digest or not isinstance(block["data"], str)
                    or len(block["data"]) > 32000):
                raise ValueError()
            decoded = base64.b64decode(block["data"], validate=True)
            if not decoded or len(decoded) > 24000:
                raise ValueError()
            data.extend(decoded)
            if len(data) > size:
                raise ValueError()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError()
        body = json.loads(data)
        if (not isinstance(body, dict) or not body or set(body) - prod.FIELDS
                or len(json.dumps(body).encode()) > 20000):
            raise ValueError()
        return body
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise HTTPException(409, "Niepełna lub uszkodzona kopia oczekiwanej zmiany.") from None


def readback_target(state):
    path = state.get("path")
    target = state.get("target")
    if not isinstance(path, str) or "?" in path:
        raise HTTPException(409, "Nieprawidłowy cel operacji.")
    if "/" in path:
        if target is not None and target != path:
            raise HTTPException(409, "Cel potwierdzenia nie zgadza się z operacją.")
        target = path
    elif (path not in {"pages", "posts"} or state["phase"] != "acknowledged"
          or not isinstance(target, str)
          or re.fullmatch(re.escape(path) + r"/[1-9][0-9]*", target) is None):
        # Never search for a guessed new page or repeat a creation/upload.
        raise HTTPException(409, "Brak pewnego identyfikatora utworzonego obiektu. Nie ponowiono zapisu.")
    prod.validate_spec(json.dumps({"path": target + "?context=edit", "method": "GET"}))
    return target


async def operation_status(args):
    operation, task_id = operation_key(args.get("text", ""))
    record = await asyncio.to_thread(server.db_checkpoint, task_id)
    state = checked_state(record)
    result = {
        "operation_id": operation, "task_id": task_id, "revision": record["revision"],
        "phase": state["phase"], "external_write_replayed": False,
        "requires_readback": state["phase"] in {"submitted", "acknowledged"},
    }
    if state["phase"] == "verified":
        result["receipt"] = safe_receipt(state, operation, task_id)
    return result


async def reconcile(args, owner_context=None):
    operation, task_id = operation_key(args.get("text", ""))
    w = server.workspace
    async with w.lock:
        if w.context is None or w.profile != prod.WP_PROFILE or w.human:
            raise HTTPException(409, "Otwórz właściwy profil i sprawdź przekazanie sterowania.")
        if owner_context is not None and owner_context is not w.context:
            raise HTTPException(409, "Sesja wygasła.")
        await w.assert_lease()
        page = w.page()
        if not page.url.startswith(prod.WP_ORIGIN + "/wp-admin/"):
            raise HTTPException(409, "Otwórz kokpit WordPress przed odczytem zwrotnym.")
        identity = (await prod.rest(page, "users/me?context=edit&_fields=id,name,slug"))["data"]
        if not isinstance(identity, dict) or identity.get("slug") != "edycjanapieraj":
            raise HTTPException(403, "Nie potwierdzono oczekiwanego konta właściciela.")
        w.last_activity = time.monotonic()
        record = await asyncio.to_thread(server.db_checkpoint, task_id)
        state = checked_state(record)
        if state["phase"] == "verified":
            return {**safe_receipt(state, operation, task_id), "already_confirmed": True}
        if state["phase"] not in {"submitted", "acknowledged"}:
            raise HTTPException(409, "Operacja była tylko przygotowana. Nie wysłano jej ponownie.")
        target = readback_target(state)
        desired = await read_desired(state.get("desired_backup"))
        after = prod.editable((await prod.rest(page, target + "?context=edit"))["data"])
        if not isinstance(after, dict):
            raise HTTPException(409, "Nieprawidłowy wynik odczytu zwrotnego.")
        for field, expected in desired.items():
            actual = after.get(field)
            if isinstance(actual, dict) and "raw" in actual:
                actual = actual["raw"]
            if actual != expected:
                raise HTTPException(409, {"code": "readback_mismatch", "field": field, "task_id": task_id})
        after_backup = await prod.backup_document(operation, "reconciled-after", after)
        receipt = {
            "ok": True, "verified": True, "target": target,
            "sha256": prod.fingerprint(after), "operation_id": operation, "task_id": task_id,
            "verification_basis": "desired_fields_observed_without_replaying_write",
            "external_write_replayed": False,
        }
        updated = {**state, "phase": "verified", "target": target,
                   "after_backup": after_backup, "receipt": receipt}
        await asyncio.to_thread(server.db_checkpoint, task_id, updated, record["revision"])
        return receipt


async def completion_action(args, automated=False, owner_context=None):
    action = args.get("action")
    if action not in {"runtime_status", "wordpress_operation_status", "wordpress_reconcile"}:
        return await _previous_action(args, automated=automated, owner_context=owner_context)
    w = server.workspace
    if owner_context is not None and owner_context is not w.context:
        raise HTTPException(409, "Sesja wygasła.")
    if action == "runtime_status":
        return {
            "version": "2.0.1", "commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
            "profile_open": w.context is not None,
            "profile": w.profile if w.context is not None else None,
            "human_control": bool(w.human) if w.context is not None else False,
            "busy": w.lock.locked(),
            "wordpress_cooldown_seconds": max(0, math.ceil(prod.WP_COOLDOWN_UNTIL - time.monotonic())),
            "capabilities": ["wordpress_rest", "wordpress_operation_status", "wordpress_reconcile",
                             "wordpress_session_status", "checkpoint", "file_fields", "download"],
            "file_limit_bytes": 8000000, "background_execution": False,
        }
    if args.get("name") != prod.WP_PROFILE:
        raise HTTPException(403, "Wymagany istniejący profil WordPress kliniki.")
    if action == "wordpress_operation_status":
        return await operation_status(args)
    return await reconcile(args, owner_context=owner_context)


server.workspace.action = completion_action

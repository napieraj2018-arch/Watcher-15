#!/usr/bin/env python3
"""Read-only Facebook lead monitor using the user's OWN encrypted AI Browser profile.

Requires an authenticated, user-created persistent browser profile and a protected
AI_BROWSER_MCP_URL. Never exports cookies to GitHub, never sends Facebook actions.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.facebook_local_monitor import (
    CONFIG, STATE, canonical_link, classify, digest, send_email, simplify,
)

PROFILE = os.environ.get("FB_WATCH_PROFILE", "Meta - Maciej - Monitoring")
POST_LIMIT = 12

def unwrap(tool_result):
    """Normalise JSON returned by an MCP tool (text or structured output)."""
    if getattr(tool_result, "isError", False):
        raise RuntimeError("Remote browser returned a tool error")
    structured = getattr(tool_result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for part in getattr(tool_result, "content", []):
        raw = getattr(part, "text", None)
        if not raw:
            continue
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            continue
    raise RuntimeError("Remote browser returned no JSON")

def result_value(data):
    return data.get("result", data) if isinstance(data, dict) else data

def as_items(data):
    value = result_value(data)
    if isinstance(value, list):
        return value
    return []

def is_login(data):
    value = result_value(data)
    if not isinstance(value, dict):
        return False
    url = str(value.get("url", "")).lower()
    content = simplify(str(value.get("text", ""))[:800])
    if any(p in url for p in ("/login", "two_step_verification", "/checkpoint")):
        return True
    if any(p in content for p in (
        "log into facebook", "zaloguj sie do facebooka",
        "email or mobile number", "password", "utworz nowe konto",
    )):
        return True
    return False

def load_remote_state():
    if not STATE.exists():
        return set(), set()
    try:
        raw = json.loads(STATE.read_text("utf-8"))
        hashes = raw.get("hashes", [])
        baselines = raw.get("baselined_sources", [])
        if not isinstance(hashes, list) or not isinstance(baselines, list):
            raise ValueError()
        return set(hashes), set(baselines)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Corrupt state; failing closed") from exc

def save_remote_state(hashes, baselines):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "version": 2,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hashes": sorted(hashes),
        "baselined_sources": sorted(baselines),
    }), encoding="utf-8")
    tmp.replace(STATE)

async def run() -> int:
    url = os.getenv("AI_BROWSER_MCP_URL", "").strip()
    if not url.startswith("https://"):
        print("CONFIG_REQUIRED: AI_BROWSER_MCP_URL must be a GitHub secret")
        return 2
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        print("CONFIG_REQUIRED: install mcp Python SDK")
        return 2

    config = json.loads(CONFIG.read_text("utf-8"))
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    hashes, baselines = load_remote_state()
    found = []
    stats = []
    started = False
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as client:
            await client.initialize()
            async def call(tool, params=None):
                return unwrap(await client.call_tool(tool, params or {}))

            profiles = as_items(await call("profile_list"))
            if PROFILE not in {p.get("name") for p in profiles}:
                print("LOGIN_REQUIRED: watcher profile does not exist yet")
                return 3
            existing_sessions = as_items(await call("browser_sessions"))
            if existing_sessions:
                print("SKIPPED: an AI Browser session is active; do not interrupt the user")
                return 0
            try:
                started_data = result_value(await call("browser_start", {
                    "profile": PROFILE, "mode": "read_only", "headless": True,
                    "start_url": "https://www.facebook.com/",
                }))
                if not isinstance(started_data, dict):
                    print("BROWSER_UNAVAILABLE")
                    return 3
                sid = started_data.get("session_id")
                if not sid:
                    print("BROWSER_UNAVAILABLE: missing session ID")
                    return 3
                started = True
                for source in sources:
                    try:
                        nav = await call("browser_navigate", {
                            "session_id": sid, "url": source["url"],
                        })
                        snap = await call("browser_snapshot", {
                            "session_id": sid, "max_text_chars": 10000,
                            "max_elements": 180,
                        })
                        if is_login(nav) or is_login(snap):
                            print(f"SOURCE {source['name']}: login_required")
                            stats.append(False)
                            continue
                        raw_links = as_items(await call("browser_links", {
                            "session_id": sid, "visible_only": True,
                            "limit": 300,
                        }))
                        links = []
                        for item in raw_links:
                            if not isinstance(item, dict):
                                continue
                            link = canonical_link(item.get("href", ""), source["url"])
                            if link and link not in links:
                                links.append(link)
                            if len(links) >= int(config.get("max_posts_per_source", POST_LIMIT)):
                                break
                        if not links:
                            print(f"SOURCE {source['name']}: no_identifiable_posts")
                            stats.append(False)
                            continue
                        new = 0
                        for link in links:
                            fingerprint = digest(link)
                            if fingerprint in hashes:
                                continue
                            # Baseline this source before sending any historical leads.
                            if source["id"] not in baselines:
                                hashes.add(fingerprint)
                                continue
                            page_nav = await call("browser_navigate", {
                                "session_id": sid, "url": link,
                            })
                            page_snap = await call("browser_snapshot", {
                                "session_id": sid, "max_text_chars": 5500,
                                "max_elements": 80,
                            })
                            if is_login(page_nav) or is_login(page_snap):
                                print("POST_LOGIN_REQUIRED; not storing incomplete scan")
                                return 3
                            text = str(result_value(page_snap).get("text", ""))[:4500]
                            category, score = classify(text)
                            if category:
                                found.append({
                                    "source": source["name"], "url": link,
                                    "text": text[:1000], "category": category,
                                    "score": score,
                                })
                            else:
                                hashes.add(fingerprint)
                            new += 1
                        stats.append(True)
                        if source["id"] not in baselines:
                            baselines.add(source["id"])
                            print(f"SOURCE {source['name']}: baseline_saved posts={len(links)}")
                        else:
                            print(f"SOURCE {source['name']}: ok links={len(links)} new={new}")
                    except Exception as exc:
                        print(f"SOURCE {source['name']}: error_{type(exc).__name__}")
                        stats.append(False)
            finally:
                if started:
                    try:
                        await call("browser_stop", {"session_id": sid})
                    except Exception:
                        print("WARNING: browser stop failed; profile may remain in use")
    if not any(stats):
        print("NO_ACCESS: no verified posts; not sending false empty reports")
        return 3
    if found:
        try:
            if not send_email(found, config):
                print("ALERT_PENDING: email not configured, match IDs kept for retry")
                save_remote_state(hashes, baselines)
                return 4
        except Exception as exc:
            print(f"EMAIL_FAILURE: {type(exc).__name__}; matching URLs not marked seen")
            save_remote_state(hashes, baselines)
            return 4
        hashes.update(digest(x["url"]) for x in found)
    save_remote_state(hashes, baselines)
    print(f"SUMMARY readable_sources={sum(stats)} alerts={len(found)} "
          f"configured_sources={len(sources)}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except Exception as exc:
        # Never log a secret-bearing MCP URL or a Facebook auth context.
        print(f"MONITOR_ERROR: {type(exc).__name__}")
        sys.exit(3)

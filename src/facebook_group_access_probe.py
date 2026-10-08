#!/usr/bin/env python3
"""One-shot, read-only verification of the owner's Facebook group access.

No automated signup, CAPTCHA solving, 2FA bypass, liking, commenting, or posting.
Requires an owner-authenticated, cloud-persisted AI Browser profile and an MCP
endpoint URL supplied solely as an environment secret. Never prints post text,
post IDs, credentials, Facebook cookies, raw URLs or private group member data.

DO NOT schedule this on Steel Cloud without an explicit usage/budget cap:
the provider's initial $30 credits do not renew.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "facebook_local_monitor.json"
MONITOR_PROFILE = "Meta - Maciej - Monitoring"
ALLOWED_HOSTS = {"www.facebook.com", "facebook.com", "m.facebook.com"}
_GROUP_PATH = re.compile(r"^/groups/(\d+)/?$")
_POST_PATH = re.compile(r"^/groups/(\d+)/(posts|permalink)/([a-zA-Z0-9_-]+)/?$")


def group_id(source: dict) -> str:
    """Take the numeric group ID from a confirmed canonical group link."""
    value = source.get("url") or ""
    parsed = urlsplit(value)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Untrusted Facebook host")
    matched = _GROUP_PATH.fullmatch(parsed.path)
    if not matched:
        raise ValueError("Source needs a canonical numeric /groups/<id>/ URL")
    return matched.group(1)


def post_reference(href: str, expected_group_id: str) -> str | None:
    """Validate that a public/link-visible permalink belongs to this group."""
    if not href:
        return None
    parsed = urlsplit(href.replace("&amp;", "&"))
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None
    found = _POST_PATH.fullmatch(parsed.path)
    if not found or found.group(1) != expected_group_id:
        return None
    return f"https://www.facebook.com/groups/{expected_group_id}/{found.group(2)}/{found.group(3)}"


def unique_group_posts(links: list[dict], expected_group_id: str) -> list[str]:
    seen = set()
    output = []
    for item in links:
        if not isinstance(item, dict):
            continue
        ref = post_reference(item.get("href", ""), expected_group_id)
        if ref and ref not in seen:
            seen.add(ref)
            output.append(ref)
    return output


def unwrap(result):
    """Handle text or structured MCP responses without leaking remote content."""
    if getattr(result, "isError", False):
        raise RuntimeError("AI Browser returned a tool error")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []):
        txt = getattr(item, "text", "")
        if not txt:
            continue
        try:
            decoded = json.loads(txt)
            if isinstance(decoded, (dict, list)):
                return decoded
        except ValueError:
            pass
    raise RuntimeError("AI Browser did not return structured data")


def value(data):
    if isinstance(data, dict):
        return data.get("result", data)
    return data


def login_shell(url: str, text: str) -> bool:
    path = urlsplit(url).path.lower()
    if any(marker in path for marker in (
        "/login", "/checkpoint", "/two_step_verification", "/recover",
    )):
        return True
    low = " ".join(text.casefold().split())
    has_password = "password" in low or "hasło" in low or "haslo" in low
    has_account_input = any(word in low for word in (
        "email address or mobile number", "email or mobile number",
        "adres e-mail", "numer telefonu",
    ))
    has_login_prompt = any(word in low for word in (
        "log in to facebook", "log into facebook",
        "zaloguj się do facebooka", "zaloguj sie do facebooka",
    ))
    return has_password and (has_account_input or has_login_prompt)


def joined_private_group(text: str) -> bool:
    """Conservative membership gate; a mere group preview is not enough."""
    low = text.casefold()
    private = ("private group" in low or "grupa prywatna" in low)
    if not private:
        return True
    join_prompt = (
        "join group", "dołącz do grupy", "dolacz do grupy",
        "request to join", "poproś o dołączenie",
    )
    return not any(phrase in low for phrase in join_prompt)


def group_access_status(
    *, canonical_url: str, final_url: str, visible_text: str,
    links: list[dict], is_private: bool, logged_in: bool,
    expected_group_id: str,
) -> tuple[str, int]:
    """No false claim of coverage if only the group header was readable."""
    refs = unique_group_posts(links, expected_group_id)
    path = urlsplit(final_url).path
    if login_shell(final_url, visible_text):
        return "login_required", 0
    if not path.startswith(f"/groups/{expected_group_id}"):
        return "unexpected_redirect", 0
    if is_private and not logged_in:
        return "authentication_required", 0
    if is_private and not joined_private_group(visible_text):
        return "membership_required", 0
    if not refs:
        return "no_visible_post_links", 0
    return ("member_visible" if is_private else "public_or_member_visible"), len(refs)


def sources_from_config(path: Path = CONFIG_PATH) -> list[dict]:
    config = json.loads(path.read_text("utf-8"))
    groups = []
    seen = set()
    for src in config["sources"]:
        if src.get("type") != "facebook_group":
            continue
        gid = group_id(src)
        if gid in seen:
            raise ValueError("Duplicate Facebook group ID")
        seen.add(gid)
        groups.append({
            "id": src["id"], "url": src["url"], "gid": gid,
            "private": "private" in str(src.get("status", "")).lower()
                       or "prywatna" in src["name"].lower(),
        })
    return groups


async def run_probe() -> int:
    mcp_url = os.environ.get("AI_BROWSER_MCP_URL", "").strip()
    if not mcp_url.startswith("https://"):
        print("SETUP_REQUIRED: store the AI Browser MCP URL as a private secret")
        return 2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    group_list = sources_from_config()
    session_id = None
    visible = 0
    try:
        async with streamable_http_client(mcp_url) as streams:
            async with ClientSession(streams[0], streams[1]) as client:
                await client.initialize()

                async def invoke(name: str, arguments: dict | None = None):
                    data = unwrap(await client.call_tool(name, arguments or {}))
                    return value(data)

                profiles = await invoke("profile_list")
                profile_names = {x.get("name") for x in profiles if isinstance(x, dict)}
                if MONITOR_PROFILE not in profile_names:
                    print("PROFILE_MISSING: one-time owner setup required")
                    return 3
                sessions = await invoke("browser_sessions")
                if sessions:
                    print("BROWSER_BUSY: no interruption of active user sessions")
                    return 4

                # One provider session only. Never create four billable sessions.
                started = await invoke("browser_start", {
                    "profile": MONITOR_PROFILE, "mode": "read_only",
                    "headless": True, "start_url": "https://www.facebook.com/",
                })
                session_id = started.get("session_id")
                if not session_id:
                    print("START_FAILED: missing browser session")
                    return 3

                home = await invoke("browser_snapshot", {
                    "session_id": session_id, "max_text_chars": 2000,
                    "max_elements": 30,
                })
                logged_in = not login_shell(home.get("url", ""), home.get("text", ""))
                if not logged_in:
                    print("LOGIN_REQUIRED: Facebook authentication is not persisted")
                    return 3

                for group in group_list:
                    try:
                        await invoke("browser_navigate", {
                            "session_id": session_id, "url": group["url"],
                        })
                        snap = await invoke("browser_snapshot", {
                            "session_id": session_id, "max_text_chars": 4000,
                            "max_elements": 80,
                        })
                        links = await invoke("browser_links", {
                            "session_id": session_id, "visible_only": True, "limit": 200,
                        })
                        state, n_posts = group_access_status(
                            canonical_url=group["url"],
                            final_url=snap.get("url", ""),
                            visible_text=snap.get("text", ""),
                            links=links,
                            is_private=group["private"], logged_in=logged_in,
                            expected_group_id=group["gid"],
                        )
                        visible += (n_posts > 0)
                        # Never print texts/URLs of private member posts.
                        print(f"GROUP {group['id']}: status={state} post_links={n_posts}")
                    except Exception as exc:
                        # Exception TYPE only: never include credential query strings.
                        print(f"GROUP {group['id']}: error={type(exc).__name__}")
    finally:
        if session_id:
            # Reconnect for cleanup: the first MCP client may already be closed.
            try:
                async with streamable_http_client(mcp_url) as cleanup_streams:
                    async with ClientSession(cleanup_streams[0], cleanup_streams[1]) as cleanup_client:
                        await cleanup_client.initialize()
                        done = await cleanup_client.call_tool(
                            "browser_stop", {"session_id": session_id}
                        )
                        unwrap(done)
                        print("SESSION_STOPPED")
            except Exception:
                print("SESSION_STOP_FAILED; check active sessions before retrying")

    print(f"PROBE_COMPLETED: groups={len(group_list)} groups_with_posts={visible}")
    return 0 if visible else 3


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run_probe()))
    except Exception as exc:
        print(f"PROBE_FAILED: {type(exc).__name__}")
        sys.exit(3)

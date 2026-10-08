#!/usr/bin/env python3
"""Privacy-minimal, no-cost notification through GitHub Issues.

On an explicitly enabled run, creates one GitHub issue per new relevant post.
Only the category, public source name and public permalink are stored in issues.
This does not access Facebook, does not disclose session cookies, and never
posts or comments on Facebook. Repository issues are PUBLIC on a public repo.
"""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.facebook_local_monitor import canonical_link, digest


def request_json(method: str, url: str, token: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "facebook-local-monitor",
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=20) as resp:
        return json.load(resp)


def notify_via_github(matches: list[dict]) -> bool:
    if os.environ.get("FB_GITHUB_ISSUE_ALERTS") != "true":
        print("GITHUB_ALERTS_DISABLED")
        return False
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        print("GITHUB_ALERTS_MISSING_AUTH")
        return False
    base = f"https://api.github.com/repos/{repo}"
    owner = repo.split("/")[0]
    assignee = os.environ.get("FB_GITHUB_ASSIGNEE", owner)
    try:
        issues = request_json("GET", base + "/issues?state=all&per_page=100", token)
    except Exception as exc:
        print(f"GITHUB_ALERT_LIST_ERROR type={type(exc).__name__}")
        return False
    seen = {m.group(1) for item in issues if isinstance(item, dict)
            for m in re.finditer(r"fbwatch:([0-9a-f]{64})", item.get("body") or "")}
    for item in matches:
        link = canonical_link(item.get("url", ""), "https://www.facebook.com/")
        if not link:
            print("GITHUB_ALERT_SKIPPED_NON_FACEBOOK_LINK")
            continue
        unique = digest(link)
        if unique in seen:
            print("GITHUB_ALERT_ALREADY_SENT")
            continue
        category = item.get("category", "INNE")
        source = item.get("source", "Facebook")
        # The public issue contains no names, quotes or other personal content.
        body = (
            f"Nowy sygnal lokalnego zapytania: **{category}**\n\n"
            f"Zrodlo: {source}\n\n"
            f"Wpis na Facebooku: {link}\n\n"
            "Odpowiedz osobiscie z wlasciwego konta, po sprawdzeniu tresci.\n\n"
            f"Powiadomienie dla @{assignee}.\n\n"
            f"<!-- fbwatch:{unique} -->\n"
        )
        payload = {
            "title": f"[FB Watch] {category}: {source}",
            "body": body,
            "assignees": [assignee],
        }
        try:
            result = request_json("POST", base + "/issues", token, payload)
            seen.add(unique)
            print(f"GITHUB_ALERT_CREATED issue={result.get('number', 'unknown')}")
        except Exception as exc:
            print(f"GITHUB_ALERT_POST_ERROR type={type(exc).__name__}")
            return False
    return True

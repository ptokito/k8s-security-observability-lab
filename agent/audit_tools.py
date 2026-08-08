"""
audit_tools.py — Query functions over a Kubernetes audit log (JSON lines).

Each function is a "tool" the agent can call. Every tool takes simple
arguments and returns a plain-text string, because a small local model
handles readable text far better than nested JSON. This design choice
(readable tool output over raw structures) comes straight from the Lab 2
finding that tool-result wording drives agent reliability.
"""

import json
from collections import Counter
from datetime import datetime

AUDIT_PATH = "audit.log"


def _load_events(path=AUDIT_PATH):
    """Read the audit log into a list of dicts, skipping any unparseable lines."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # A truncated final line can happen if the log was copied mid-write.
                continue
    return events


def find_denied_requests(_input=""):
    """Return every request the API server refused (403 Forbidden / denied).
    This is the tool that surfaces the blocked attacks the health dashboard never shows."""
    events = _load_events()
    denied = []
    for e in events:
        status = e.get("responseStatus", {}) or {}
        code = status.get("code")
        decision = (e.get("annotations", {}) or {}).get("authorization.k8s.io/decision")
        if code == 403 or decision == "forbid" or status.get("status") == "Failure":
            user = (e.get("user", {}) or {}).get("username", "unknown")
            ref = e.get("objectRef", {}) or {}
            target = f"{ref.get('resource','?')}/{ref.get('name','?')} in ns={ref.get('namespace','?')}"
            reason = status.get("message", "")[:160]
            denied.append(f"- user={user} verb={e.get('verb','?')} target={target} code={code} reason={reason}")
    if not denied:
        return "No denied or failed requests found in the audit log."
    return f"Found {len(denied)} denied/failed request(s):\n" + "\n".join(denied[:25])


def who_accessed_secrets(_input=""):
    """Return which identities read, listed, or watched Secrets, and how many times each."""
    events = _load_events()
    hits = Counter()
    for e in events:
        ref = e.get("objectRef", {}) or {}
        if ref.get("resource") == "secrets":
            user = (e.get("user", {}) or {}).get("username", "unknown")
            hits[f"{user} ({e.get('verb','?')})"] += 1
    if not hits:
        return "No access to Secrets was recorded in the audit log."
    lines = [f"- {k}: {v} time(s)" for k, v in hits.most_common(20)]
    return "Secret access by identity:\n" + "\n".join(lines)


def summarize_activity(_input=""):
    """High-level tally: total events, top verbs, top users, top resources touched."""
    events = _load_events()
    verbs, users, resources = Counter(), Counter(), Counter()
    for e in events:
        verbs[e.get("verb", "?")] += 1
        users[(e.get("user", {}) or {}).get("username", "unknown")] += 1
        ref = e.get("objectRef", {}) or {}
        if ref.get("resource"):
            resources[ref["resource"]] += 1
    top = lambda c: ", ".join(f"{k}={v}" for k, v in c.most_common(5))
    return (
        f"Total events: {len(events)}\n"
        f"Top verbs: {top(verbs)}\n"
        f"Top users: {top(users)}\n"
        f"Top resources: {top(resources)}"
    )


def find_by_name(name=""):
    """Return all audit entries whose target object name contains the given string.
    Useful for tracing a specific pod, e.g. the 'evil-' attack pods."""
    name = (name or "").strip()
    if not name:
        return "Please provide a name substring to search for (e.g. 'evil')."
    events = _load_events()
    matches = []
    for e in events:
        ref = e.get("objectRef", {}) or {}
        obj_name = ref.get("name", "") or ""
        if name.lower() in obj_name.lower():
            status = e.get("responseStatus", {}) or {}
            outcome = status.get("code", "?")
            user = (e.get("user", {}) or {}).get("username", "unknown")
            matches.append(f"- {e.get('verb','?')} {ref.get('resource','?')}/{obj_name} by {user} -> code {outcome}")
    if not matches:
        return f"No audit entries found for objects matching '{name}'."
    return f"Found {len(matches)} entr(y/ies) matching '{name}':\n" + "\n".join(matches[:25])


# Registry the agent reads to know what it can call.
TOOLS = {
    "find_denied_requests": {
        "fn": find_denied_requests,
        "description": "List all requests the API server denied or that failed (403 Forbidden, admission rejections). Use for questions about blocked, denied, rejected, or forbidden actions and attacks.",
        "takes_arg": False,
    },
    "who_accessed_secrets": {
        "fn": who_accessed_secrets,
        "description": "Show which users or service accounts accessed Kubernetes Secrets and how often. Use for questions about secrets access.",
        "takes_arg": False,
    },
    "summarize_activity": {
        "fn": summarize_activity,
        "description": "Give a high-level summary of all audit activity: total events, top verbs, top users, top resources. Use for broad 'what happened' or 'summarize' questions.",
        "takes_arg": False,
    },
    "find_by_name": {
        "fn": find_by_name,
        "description": "Find all audit entries for objects whose name contains a given string. Requires an argument: the name to search for. Use to trace a specific named pod or resource.",
        "takes_arg": True,
    },
}

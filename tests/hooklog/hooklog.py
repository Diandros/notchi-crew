#!/usr/bin/env python3
"""Protokolliert jedes Claude-Code-Hook-Event als JSON-Zeile. Testwerkzeug fuer notchi-crew."""
import json, os, sys, time
d = json.load(sys.stdin)
keep = {k: d.get(k) for k in ("hook_event_name", "session_id", "agent_id", "agent_type", "tool_name", "transcript_path", "cwd", "permission_mode")}
keep["t"] = time.time()
keep["ppid"] = os.getppid()
log = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), "log", "events.jsonl")
with open(log, "a") as f:
    f.write(json.dumps(keep) + "\n")

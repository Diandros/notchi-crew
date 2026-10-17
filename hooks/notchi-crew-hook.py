#!/usr/bin/env python3
"""notchi-crew: zeigt Claude-Code-Subagenten als eigene Figuren in Notchi.

Läuft als zusätzlicher Claude-Code-Hook neben Notchis eigenem Skript. Verarbeitet
nur Events, die in einem Subagenten feuern (Feld agent_type gesetzt), und schickt
sie mit einer eigenen session_id und einem eigenen cwd an Notchis Unix-Socket.
Notchi legt daraus eine zweite Sitzung an, deren Label der Agentenname ist.

Abbildung (Stand Notchi 1.2.7 und HEAD e6f8b8a, siehe docs/analyse-notchi.md):
  SubagentStart -> UserPromptSubmit, status processing   (Figur erscheint sofort)
  PreToolUse    -> PreToolUse,       status running_tool
  PostToolUse   -> PostToolUse,      status processing
  SubagentStop  -> SubagentStop,     status waiting_for_input, danach SessionEnd

Alles andere wird ignoriert. Bricht nie den Hook-Lauf ab (immer Exit 0).
"""
import json
import os
import socket
import subprocess
import sys
import time

LINGER_SECONDS = float(os.environ.get("NOTCHI_CREW_LINGER", "4"))
TIMEOUT = 0.5


def socket_path():
    """Erster vorhandener Notchi-Socket: HEAD-Pfad, Rückfall, dann 1.2.7."""
    env = os.environ.get("NOTCHI_SOCKET_PATH")
    home = os.path.expanduser("~")
    candidates = [
        env,
        os.path.join(home, "Library", "Application Support", "Notchi", "notchi.sock"),
        os.path.join(home, ".notchi", "notchi.sock"),
        "/tmp/notchi.sock",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                import stat
                if stat.S_ISSOCK(os.stat(path).st_mode):
                    return path
            except OSError:
                continue
    return None


def send(path, payload):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect(path)
        sock.sendall(json.dumps(payload).encode())
        sock.close()
    except OSError:
        pass


def build(event_name, status, data, agent_session_id, agent_cwd):
    payload = {
        "provider": "claude",
        "session_id": agent_session_id,
        "transcript_path": "",
        "cwd": agent_cwd,
        "event": event_name,
        "status": status,
        "interactive": False,
        "permission_mode": data.get("permission_mode", "default"),
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
    }
    tool = data.get("tool_name")
    if tool:
        payload["tool"] = tool
    tool_use_id = data.get("tool_use_id")
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    tool_input = data.get("tool_input")
    if tool_input:
        payload["tool_input"] = tool_input
    return payload


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if not isinstance(data, dict):
        return

    agent_type = data.get("agent_type")
    agent_id = data.get("agent_id")
    event = data.get("hook_event_name", "")
    if not agent_type or not agent_id:
        return

    # Zweiter Aufruf nur für das verzögerte SessionEnd (siehe unten).
    if "--end" in sys.argv:
        path = socket_path()
        if path:
            time.sleep(LINGER_SECONDS)
            send(path, build("SessionEnd", "ended", data,
                             data["_crew_session_id"], data["_crew_cwd"]))
        return

    path = socket_path()
    if not path:
        return

    parent_session = data.get("session_id", "")
    parent_cwd = data.get("cwd", "") or os.getcwd()
    agent_session_id = f"{parent_session}:agent:{agent_id}"
    agent_cwd = os.path.join(parent_cwd, agent_type)

    if event == "SubagentStart":
        send(path, build("UserPromptSubmit", "processing", data, agent_session_id, agent_cwd))
    elif event == "PreToolUse":
        send(path, build("PreToolUse", "running_tool", data, agent_session_id, agent_cwd))
    elif event == "PostToolUse":
        send(path, build("PostToolUse", "processing", data, agent_session_id, agent_cwd))
    elif event == "SubagentStop":
        send(path, build("SubagentStop", "waiting_for_input", data, agent_session_id, agent_cwd))
        # SessionEnd verzögert aus einem abgekoppelten Prozess, damit die Figur
        # kurz idle steht, bevor sie verschwindet, und der Hook sofort zurückkehrt.
        data["_crew_session_id"] = agent_session_id
        data["_crew_cwd"] = agent_cwd
        try:
            subprocess.Popen(
                [sys.executable, "-I", os.path.abspath(__file__), "--end"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            ).stdin.write(json.dumps(data).encode())
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)

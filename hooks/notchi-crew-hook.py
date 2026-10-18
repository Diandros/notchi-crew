#!/usr/bin/env python3
"""notchi-crew: zeigt Claude-Code-Subagenten als eigene Figuren in Notchi.

Läuft als zusätzlicher Claude-Code-Hook neben Notchis eigenem Skript. Verarbeitet
nur Events, die in einem Subagenten feuern (Feld agent_type gesetzt), und schickt
sie mit einer eigenen session_id und einem eigenen cwd an Notchis Unix-Socket.
Notchi legt daraus eine zweite Sitzung an, deren Label der Agentenname ist.

Stufe 1 (17.10.2026): eine Figur je Agent.
  SubagentStart -> UserPromptSubmit, status processing   (Figur erscheint sofort)
  PreToolUse    -> PreToolUse,       status running_tool
  PostToolUse   -> PostToolUse,      status processing
  SubagentStop  -> SubagentStop,     status waiting_for_input, danach SessionEnd

Stufe 1b (18.10.2026): Tische. Laufen zwei oder mehr Agenten desselben Typs
gleichzeitig, verschwinden ihre Einzelfiguren und ein Tisch je Typ übernimmt,
eine Figur mit dem Label des Typs. Der Tisch meldet als "Werkzeug" eine
Zusammenfassung, die Notchi in der Sitzungszeile und der Aktivitätsliste
anzeigt, etwa "3 Lektoren · Read notizen.md · Grep · Bash". Er bleibt bei
der Arbeit, solange noch ein Agent des Typs läuft, und verschwindet erst mit
dem letzten. Die aktiven Agenten je Elternsitzung stehen in einer kleinen
Zustandsdatei unter /tmp/notchi-crew/ (Pfad über NOTCHI_CREW_STATE_DIR).

Alles andere wird ignoriert. Bricht nie den Hook-Lauf ab (immer Exit 0).
"""
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time

LINGER_SECONDS = float(os.environ.get("NOTCHI_CREW_LINGER", "4"))
STATE_DIR = os.environ.get("NOTCHI_CREW_STATE_DIR", "/tmp/notchi-crew")
STALE_SECONDS = 2 * 60 * 60  # Agenten ohne Event seit zwei Stunden gelten als tot
TIMEOUT = 0.5
SUMMARY_MAX = 90

# Einzahl und Mehrzahl für die Tischzeile; unbekannte Typen bekommen "n × <typ>".
PLURAL = {
    "deep-researcher": ("Researcher", "Researcher"),
    "dokument-autor": ("Autor", "Autoren"),
    "lektor": ("Lektor", "Lektoren"),
    "general-purpose": ("Agent", "Agenten"),
    "Explore": ("Kundschafter", "Kundschafter"),
    "Plan": ("Planer", "Planer"),
}


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


def build(event_name, status, data, session_id, cwd, tool=None, tool_input=None):
    payload = {
        "provider": "claude",
        "session_id": session_id,
        "transcript_path": "",
        "cwd": cwd,
        "event": event_name,
        "status": status,
        "interactive": False,
        "permission_mode": data.get("permission_mode", "default"),
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
    }
    if tool:
        payload["tool"] = tool
    tool_use_id = data.get("tool_use_id")
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    if tool_input:
        payload["tool_input"] = tool_input
    return payload


# --- Zustand je Elternsitzung -------------------------------------------------

class State:
    """Aktive Agenten einer Elternsitzung, gesperrt über fcntl, damit parallele
    Hook-Prozesse sich nicht gegenseitig überschreiben."""

    def __init__(self, parent_session):
        os.makedirs(STATE_DIR, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", parent_session or "unbekannt")
        self.path = os.path.join(STATE_DIR, f"{safe}.json")
        self.lock = open(self.path + ".lock", "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.agents = self.data.setdefault("agents", {})
        self.tables = self.data.setdefault("tables", {})
        now = time.time()
        for aid in [a for a, v in self.agents.items() if now - v.get("ts", now) > STALE_SECONDS]:
            del self.agents[aid]

    def of_type(self, agent_type):
        return {a: v for a, v in self.agents.items() if v.get("type") == agent_type}

    def close(self):
        try:
            if self.agents or any(self.tables.values()):
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f)
            else:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()


def activity(tool, tool_input):
    """Kurzform 'Read Datei.md', 'Grep muster', 'Bash', aus Werkzeug und Eingabe."""
    if not tool:
        return None
    detail = ""
    if isinstance(tool_input, dict):
        if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            detail = os.path.basename(str(tool_input.get("file_path", "") or tool_input.get("notebook_path", "")))
        elif tool == "Grep":
            detail = str(tool_input.get("pattern", ""))
        elif tool == "Glob":
            detail = str(tool_input.get("pattern", ""))
        elif tool in ("WebSearch",):
            detail = str(tool_input.get("query", ""))
        elif tool == "Agent":
            detail = str(tool_input.get("subagent_type", "") or tool_input.get("description", ""))
    detail = detail.strip()
    if len(detail) > 28:
        detail = detail[:27] + "…"
    return f"{tool} {detail}".strip()


def summary(agent_type, members):
    n = len(members)
    label = PLURAL.get(agent_type)
    head = f"{n} {label[0] if n == 1 else label[1]}" if label else f"{n} × {agent_type}"
    parts = []
    for v in sorted(members.values(), key=lambda v: v.get("ts", 0)):
        a = v.get("activity")
        if a and a not in parts:
            parts.append(a)
    text = " · ".join([head] + parts)
    if len(text) > SUMMARY_MAX:
        text = text[:SUMMARY_MAX - 1] + "…"
    return text


def delayed_end(data, session_id, cwd):
    """SessionEnd verzögert aus einem abgekoppelten Prozess, damit die Figur
    kurz idle steht, bevor sie verschwindet, und der Hook sofort zurückkehrt."""
    data = dict(data)
    data["_crew_session_id"] = session_id
    data["_crew_cwd"] = cwd
    try:
        subprocess.Popen(
            [sys.executable, "-I", os.path.abspath(__file__), "--end"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        ).stdin.write(json.dumps(data).encode())
    except (OSError, ValueError):
        pass


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

    # Zweiter Aufruf nur für das verzögerte SessionEnd.
    if "--end" in sys.argv:
        path = socket_path()
        if path:
            time.sleep(LINGER_SECONDS)
            send(path, build("SessionEnd", "ended", data, data["_crew_session_id"], data["_crew_cwd"]))
        return

    path = socket_path()
    if not path:
        return

    parent_session = data.get("session_id", "")
    parent_cwd = data.get("cwd", "") or os.getcwd()
    single_id = f"{parent_session}:agent:{agent_id}"
    table_id = f"{parent_session}:table:{agent_type}"
    cwd = os.path.join(parent_cwd, agent_type)  # Label: der Agententyp
    tool = data.get("tool_name")
    tool_input = data.get("tool_input")

    state = State(parent_session)
    try:
        members = state.of_type(agent_type)
        table_open = bool(state.tables.get(agent_type))

        if event == "SubagentStart":
            state.agents[agent_id] = {"type": agent_type, "ts": time.time(), "activity": None}
            members = state.of_type(agent_type)
            if table_open:
                send(path, build("PostToolUse", "processing", data, table_id, cwd, tool=summary(agent_type, members)))
            elif len(members) >= 2:
                # Zweiter Agent desselben Typs: Einzelfiguren gehen, der Tisch kommt.
                for other in members:
                    if other != agent_id:
                        send(path, build("SessionEnd", "ended", data, f"{parent_session}:agent:{other}", cwd))
                state.tables[agent_type] = True
                send(path, build("UserPromptSubmit", "processing", data, table_id, cwd, tool=summary(agent_type, members)))
            else:
                send(path, build("UserPromptSubmit", "processing", data, single_id, cwd))

        elif event in ("PreToolUse", "PostToolUse"):
            entry = state.agents.setdefault(agent_id, {"type": agent_type, "activity": None})
            entry["ts"] = time.time()
            if event == "PreToolUse":
                entry["activity"] = activity(tool, tool_input)
            members = state.of_type(agent_type)
            status = "running_tool" if event == "PreToolUse" else "processing"
            if table_open:
                send(path, build(event, status, data, table_id, cwd, tool=summary(agent_type, members)))
            else:
                send(path, build(event, status, data, single_id, cwd, tool=tool, tool_input=tool_input))

        elif event == "SubagentStop":
            state.agents.pop(agent_id, None)
            members = state.of_type(agent_type)
            if table_open:
                if members:
                    send(path, build("PostToolUse", "processing", data, table_id, cwd, tool=summary(agent_type, members)))
                else:
                    state.tables[agent_type] = False
                    send(path, build("SubagentStop", "waiting_for_input", data, table_id, cwd))
                    delayed_end(data, table_id, cwd)
            else:
                send(path, build("SubagentStop", "waiting_for_input", data, single_id, cwd))
                delayed_end(data, single_id, cwd)
    finally:
        state.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)

#!/usr/bin/env python3
"""Testet notchi-crew-hook.py gegen einen Fake-Socket: Einzelfiguren, Tische, Auflösung.

Aufruf: python3 -I tests/fakesocket/test_tische.py [Pfad zum Hook]
Startet einen Unix-Socket-Server in einem temporären Ordner, speist Hook-Events
über stdin ein und prüft die Reihenfolge der Nachrichten, die Notchi bekäme.
Schreibt nichts außerhalb des temporären Ordners.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HOOK = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "notchi-crew-hook.py")
HOOK = os.path.abspath(HOOK)
TMP = tempfile.mkdtemp(prefix="notchi-crew-test-")
SOCK = os.path.join(TMP, "notchi.sock")
STATE = os.path.join(TMP, "state")
received = []


def server():
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(16)
    srv.settimeout(0.2)
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        buf = b""
        conn.settimeout(0.5)
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        conn.close()
        try:
            received.append(json.loads(buf.decode()))
        except ValueError:
            received.append({"_raw": buf.decode(errors="replace")})
    srv.close()


def fire(event, agent_id, agent_type, tool=None, tool_input=None):
    data = {"session_id": "eltern", "cwd": "/projekt", "hook_event_name": event,
            "agent_id": agent_id, "agent_type": agent_type, "permission_mode": "bypassPermissions"}
    if tool:
        data["tool_name"] = tool
        data["tool_use_id"] = f"tu-{agent_id}-{len(received)}"
    if tool_input:
        data["tool_input"] = tool_input
    env = dict(os.environ, NOTCHI_SOCKET_PATH=SOCK, NOTCHI_CREW_STATE_DIR=STATE, NOTCHI_CREW_LINGER="0.3")
    subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(data).encode(), env=env, timeout=10)
    time.sleep(0.15)


def msgs():
    return [(m.get("event"), m.get("session_id"), m.get("tool")) for m in received]


stop = threading.Event()
t = threading.Thread(target=server, daemon=True)
t.start()
time.sleep(0.2)
fehler = []


def erwarte(bedingung, text):
    if not bedingung:
        fehler.append(text)
        print("FEHLT:", text)
    else:
        print("ok:   ", text)


# 1. Ein einzelner Lektor: Einzelfigur wie in Stufe 1.
fire("SubagentStart", "L1", "lektor")
fire("PreToolUse", "L1", "lektor", "Read", {"file_path": "/projekt/docs/notizen.md"})
erwarte(msgs()[0] == ("UserPromptSubmit", "eltern:agent:L1", None), "einzelner Agent erscheint als Einzelfigur")
erwarte(msgs()[1][0:2] == ("PreToolUse", "eltern:agent:L1") and msgs()[1][2] == "Read", "Einzelfigur bekommt das echte Werkzeug")

# 2. Zweiter Lektor: Einzelfigur endet, Tisch entsteht mit Zähler.
fire("SubagentStart", "L2", "lektor")
ev = msgs()[2:]
erwarte(("SessionEnd", "eltern:agent:L1", None) in ev, "Einzelfigur L1 wird beendet, wenn L2 startet")
tisch = [m for m in ev if m[1] == "eltern:table:lektor"]
erwarte(tisch and tisch[0][0] == "UserPromptSubmit" and tisch[0][2].startswith("2 Lektoren"), f"Tisch entsteht mit '2 Lektoren': {tisch}")
erwarte("Read notizen.md" in (tisch[0][2] or ""), "Tisch zeigt die Aktivität des ersten Agenten mit Dateinamen")

# 3. Werkzeuge beider Agenten laufen über den Tisch, Einzelsitzungen bleiben still.
n0 = len(received)
fire("PreToolUse", "L2", "lektor", "Grep", {"pattern": "status/"})
fire("PreToolUse", "L1", "lektor", "Bash", {"command": "python3 pruefen.py"})
neu = msgs()[n0:]
erwarte(all(m[1] == "eltern:table:lektor" for m in neu), "nach dem Tisch gehen alle Events an den Tisch")
erwarte(any("Grep status/" in (m[2] or "") and "Bash" in (m[2] or "") for m in neu), f"Zusammenfassung nennt beide Aktivitäten: {neu[-1][2]}")

# 4. Dritter Lektor stößt dazu: Zähler 3.
n0 = len(received)
fire("SubagentStart", "L3", "lektor")
erwarte(msgs()[n0][1] == "eltern:table:lektor" and msgs()[n0][2].startswith("3 Lektoren"), "dritter Agent erhöht den Zähler auf 3 ohne neue Figur")

# 5. Ein anderer Typ bleibt eine Einzelfigur.
n0 = len(received)
fire("SubagentStart", "A1", "dokument-autor")
erwarte(msgs()[n0] == ("UserPromptSubmit", "eltern:agent:A1", None), "anderer Typ bekommt weiter eine Einzelfigur")

# 6. Zwei Lektoren stoppen: Tisch bleibt bei der Arbeit mit Zähler 1.
n0 = len(received)
fire("SubagentStop", "L1", "lektor")
fire("SubagentStop", "L2", "lektor")
ev = msgs()[n0:]
erwarte(all(m[0] == "PostToolUse" and m[1] == "eltern:table:lektor" for m in ev), "Tisch bleibt bei der Arbeit, solange ein Lektor läuft")
erwarte(ev and ev[-1][2].startswith("1 Lektor"), f"Zähler fällt auf 1: {ev[-1][2]}")

# 7. Letzter Lektor stoppt: Tisch idle, dann SessionEnd.
n0 = len(received)
fire("SubagentStop", "L3", "lektor")
time.sleep(0.8)
ev = msgs()[n0:]
erwarte(ev and ev[0] == ("SubagentStop", "eltern:table:lektor", None), "letzter Stop setzt den Tisch auf idle")
erwarte(("SessionEnd", "eltern:table:lektor", None) in ev, "verzögertes SessionEnd räumt den Tisch ab")

# 8. Einzelner Autor stoppt wie in Stufe 1.
n0 = len(received)
fire("SubagentStop", "A1", "dokument-autor")
time.sleep(0.8)
ev = msgs()[n0:]
erwarte(ev[0] == ("SubagentStop", "eltern:agent:A1", None) and ("SessionEnd", "eltern:agent:A1", None) in ev, "Einzelfigur stoppt und verschwindet")

# 9. Nach dem Lauf ist die Zustandsdatei weg (keine Agenten, keine Tische).
erwarte(not [f for f in os.listdir(STATE) if f.endswith(".json")], "Zustandsdatei wird am Ende entfernt")

# 10. Hauptsitzungs-Events ohne agent_type werden ignoriert.
n0 = len(received)
env = dict(os.environ, NOTCHI_SOCKET_PATH=SOCK, NOTCHI_CREW_STATE_DIR=STATE)
subprocess.run([sys.executable, "-I", HOOK], input=json.dumps({"session_id": "eltern", "cwd": "/projekt", "hook_event_name": "PreToolUse", "tool_name": "Read"}).encode(), env=env, timeout=10)
time.sleep(0.2)
erwarte(len(received) == n0, "Events der Hauptsitzung werden ignoriert")

stop.set()
t.join(timeout=2)
print()
print(f"{len(received)} Nachrichten, {len(fehler)} Fehler, Ordner {TMP}")
sys.exit(1 if fehler else 0)

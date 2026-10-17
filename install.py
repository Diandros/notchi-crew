#!/usr/bin/env python3
"""Installiert oder entfernt den notchi-crew-Hook in Claude Code.

Aufruf:
  python3 -I install.py            installieren oder aktualisieren
  python3 -I install.py --uninstall
  python3 -I install.py --status

Verhalten nach dem Muster von Notchis eigenem Installer (HookInstaller.swift):
additiv, idempotent, eigene Einträge am Marker erkannt, fremde Einträge bleiben
unberührt. Vor jedem Schreiben entsteht ein datiertes Backup der settings.json.
"""
import json
import os
import shutil
import stat
import sys
import time

MARKER = "notchi-crew-hook.py"
EVENTS = {
    "SubagentStart": None,
    "PreToolUse": "*",
    "PostToolUse": "*",
    "SubagentStop": None,
}
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "hooks", MARKER)


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def command():
    return 'python3 -I "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/%s"' % MARKER


def is_ours(hook):
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} ist kein JSON-Objekt, breche ab.")
    return data


def save(path, data):
    if os.path.exists(path):
        backup = f"{path}.notchi-crew-backup-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def install():
    cfg = config_dir()
    hooks_dir = os.path.join(cfg, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target = os.path.join(hooks_dir, MARKER)
    with open(SOURCE, "rb") as f:
        src = f.read()
    current = open(target, "rb").read() if os.path.exists(target) else None
    if current != src:
        with open(target, "wb") as f:
            f.write(src)
        print(f"Skript geschrieben: {target}")
    os.chmod(target, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    settings_path = os.path.join(cfg, "settings.json")
    data = load(settings_path)
    hooks = data.setdefault("hooks", {})
    changed = False
    for event, matcher in EVENTS.items():
        groups = hooks.setdefault(event, [])
        found = False
        for group in groups:
            for hook in group.get("hooks", []):
                if is_ours(hook):
                    found = True
                    if hook.get("command") != command():
                        hook["command"] = command()
                        changed = True
        if not found:
            group = {"hooks": [{"type": "command", "command": command()}]}
            if matcher:
                group["matcher"] = matcher
            groups.append(group)
            changed = True
    if changed:
        save(settings_path, data)
        print(f"Hook-Einträge gesetzt in {settings_path}")
    else:
        print("Hook-Einträge waren schon aktuell.")


def uninstall():
    cfg = config_dir()
    settings_path = os.path.join(cfg, "settings.json")
    data = load(settings_path)
    hooks = data.get("hooks", {})
    changed = False
    for event in list(hooks.keys()):
        kept = []
        for group in hooks[event]:
            inner = [h for h in group.get("hooks", []) if not is_ours(h)]
            if len(inner) != len(group.get("hooks", [])):
                changed = True
            if inner:
                group["hooks"] = inner
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
            changed = True
    if not hooks and "hooks" in data:
        del data["hooks"]
    if changed:
        save(settings_path, data)
        print("Hook-Einträge entfernt.")
    else:
        print("Keine eigenen Hook-Einträge gefunden.")
    target = os.path.join(cfg, "hooks", MARKER)
    if os.path.exists(target):
        print(f"Skript bleibt liegen, bitte von Hand entfernen: {target}")


def status():
    cfg = config_dir()
    settings_path = os.path.join(cfg, "settings.json")
    data = load(settings_path)
    hooks = data.get("hooks", {})
    for event in EVENTS:
        ours = any(is_ours(h) for g in hooks.get(event, []) for h in g.get("hooks", []))
        print(f"{event:15} {'eingetragen' if ours else 'fehlt'}")
    target = os.path.join(cfg, "hooks", MARKER)
    print(f"Skript: {'vorhanden' if os.path.exists(target) else 'fehlt'} ({target})")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    elif "--status" in sys.argv:
        status()
    else:
        install()

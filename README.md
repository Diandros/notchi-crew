# notchi-crew

Mod für [Notchi](https://github.com/sk-ruban/notchi): Claude-Code-Subagenten (hier `deep-researcher`, `dokument-autor`, `lektor`) erscheinen als eigene Figuren mit eigenem Namen auf Notchis Grasinsel. Ohne Fork, ohne Änderung an Notchi.

Projektstart 17.10.2026. Die technische Analyse liegt unter `docs/analyse-notchi.md`.

## Stand

- **Stufe 1 (fertig, 17.10.2026):** `hooks/notchi-crew-hook.py` zeigt jeden Subagenten als eigene Sitzung im Claude-Look. Label ist der `agent_type`.
- **Stufe 2 (offen):** Issue und Pull Request bei Notchi für Sprite-Packs (Familie aus dem Payload, Bilder aus einem Ordner).
- **Stufe 3 (offen):** eigene Sprites je Agent (Sprite-Sheets 384 mal 64 Pixel, sechs Frames, Namensschema wie Notchi).

## Wie es funktioniert

Claude Code feuert Hooks auch innerhalb von Subagenten und liefert dort `agent_id` und `agent_type` mit (belegt in `tests/hooklog/README.md`). Der Hook läuft als zusätzlicher Eintrag neben Notchis eigenem Skript, verarbeitet nur Events mit `agent_type` und schickt sie an Notchis Socket mit

- `session_id` = `<eltern-id>:agent:<agent_id>`, damit Notchi eine eigene Sitzung anlegt,
- `cwd` = `<eltern-cwd>/<agent_type>`, damit das Label der Agentenname ist,
- `interactive: false`, damit keine Töne, kein Dateiwächter und keine Emotionsanalyse anspringen.

Abbildung der Events: `SubagentStart` geht als `UserPromptSubmit` (Figur erscheint sofort), `PreToolUse` und `PostToolUse` unverändert, `SubagentStop` unverändert und danach, aus einem abgekoppelten Prozess, nach `NOTCHI_CREW_LINGER` Sekunden (Standard 4) ein `SessionEnd`, damit die Figur wieder verschwindet.

Socket-Pfade werden in dieser Reihenfolge geprüft: `NOTCHI_SOCKET_PATH`, `~/Library/Application Support/Notchi/notchi.sock` (Notchi HEAD), `~/.notchi/notchi.sock`, `/tmp/notchi.sock` (Notchi 1.2.7).

## Installation

    python3 -I install.py            # installieren oder aktualisieren
    python3 -I install.py --status
    python3 -I install.py --uninstall

Der Installer kopiert das Skript nach `~/.claude/hooks/notchi-crew-hook.py` und trägt es in `~/.claude/settings.json` für `SubagentStart`, `PreToolUse`, `PostToolUse` und `SubagentStop` ein. Er arbeitet wie Notchis eigener Installer: additiv, idempotent, eigene Einträge am Marker `notchi-crew-hook.py` erkannt, fremde Einträge unberührt, datiertes Backup vor jedem Schreiben. Notchis Installer wiederum lässt die Einträge der Mod stehen, weil er nur seinen eigenen Marker `notchi-hook.sh` kennt (siehe Analyse, Abschnitt Hook-Installer).

## Bekannte Grenzen

- Das Haupt-Maskottchen spiegelt die Subagenten-Arbeit weiterhin mit, weil Notchis eigener Hook dieselben Events unter der Eltern-ID schickt. Das lässt sich ohne Pull Request nicht abstellen.
- In der geschlossenen Notch zeigt nur der rechte Slot ("latest") eine Figur; ein aktiver Subagent verdrängt dort das Haupt-Maskottchen. Alle Figuren gleichzeitig sieht man im ausgeklappten Panel.
- Pro Hook-Event ein zusätzlicher Python-Prozess neben Notchis eigenem.

## Tests

- `tests/hooklog/`: schneidet die Hook-Felder eines echten Claude-Code-Laufs mit.
- Der Hook lässt sich ohne Notchi gegen einen Fake-Socket prüfen: `NOTCHI_SOCKET_PATH=<pfad>` setzen und Events per stdin einspeisen.

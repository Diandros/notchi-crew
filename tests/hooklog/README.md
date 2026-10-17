# hooklog: Testwerkzeug für Hook-Events

Protokolliert jedes Claude-Code-Hook-Event als JSON-Zeile nach `log/events.jsonl`, reduziert auf die Felder, die für notchi-crew zählen (`hook_event_name`, `session_id`, `agent_id`, `agent_type`, `tool_name`, `transcript_path`, `cwd`, `permission_mode`).

Aufruf aus diesem Ordner:

    claude -p "Starte genau einen Subagenten vom Typ Explore mit dem Auftrag: fuehre den Bash-Befehl 'ls' im aktuellen Verzeichnis aus und berichte die Dateinamen. Danach antworte nur mit: fertig." --model haiku --permission-mode bypassPermissions --allowedTools "Agent,Bash,Read,Glob" < /dev/null

Befund vom 17.10.2026 (Claude Code 2.1.296): Alle Events innerhalb eines Subagenten tragen dieselbe `session_id` und denselben `transcript_path` wie die Elternsitzung, zusätzlich `agent_id` (eindeutig pro Lauf) und `agent_type` (Name der Agentendefinition, etwa `Explore`). Der Lauf eines Subagenten wird von `SubagentStart` und `SubagentStop` eingerahmt, beide mit `agent_id` und `agent_type`. Events der Hauptsitzung haben beide Felder leer.

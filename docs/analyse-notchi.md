# Technische Analyse Notchi (Stand e6f8b8a, 05.10.2026)

Grundlage für notchi-crew. Zeilenangaben beziehen sich auf den Klon unter `~/Developer/notchi`, Pfade auf `notchi/notchi/`. Installiert auf dem Mac ist v1.2.7 (19.09.2026). Erstellt am 17.10.2026.

## Zwei Socket-Pfade

- HEAD: `~/Library/Application Support/Notchi/notchi.sock`, Rückfall `~/.notchi/notchi.sock` bei zu langem Pfad (`Services/SocketServer.swift` Z. 23 bis 28). Der Pfad wird beim Installieren ins Hook-Skript geschrieben (`Services/HookFile.swift` Z. 5 bis 12).
- v1.2.7: fest `/tmp/notchi.sock` (`SocketServer.swift` Z. 17 in v1.2.7), so steht es auch in `~/.claude/hooks/notchi-hook.sh` Z. 4.
- Folge: Die Mod prüft erst App Support, dann `/tmp`.

## Socket-Protokoll

- Ein JSON-Objekt pro Verbindung, Ende durch EOF, kein Zeilenumbruch, kein Längenpräfix (`SocketServer.swift` Z. 314, 340 bis 349). Lesetimeout 0,5 s (Z. 18, 333). Client schließt nach `sendall`; nur bei erwarteter Antwort `shutdown(SHUT_WR)` und lesen (`Resources/notchi-hook.sh` Z. 151 bis 164).
- Dekodierte Felder (`Models/HookEvent.swift` Z. 77 bis 118): `provider`, `session_id`, `transcript_path`, `cwd`, `event`, `status`, `tool`, `tool_input`, `tool_use_id`, `user_prompt`, `permission_mode`, `permission_suggestions`, `interactive`, `claude_process_id`, `codex_process_id`, `codex_origin`, `devin_process_id`, `has_attachments`, `last_assistant_message`.
- Pflicht: `session_id`, `cwd`, `event`, `status` (Z. 100 bis 104). `pid` und `tty` werden nicht dekodiert.
- Unbekannte Felder werden ignoriert. `agent_id` und `agent_type` können mitgeschickt werden, ohne dass etwas bricht.
- `provider` fehlt: Rückfall `claude` (Z. 99). `provider` unbekannt: `DecodingError`, Nachricht wird verworfen ("Failed to parse event", Z. 314 bis 317).
- Unbekanntes `event`: Adapter liefert `nil` (`Services/ClaudeProviderAdapter.swift` Z. 30 bis 32), Coordinator loggt "Dropped unsupported hook event" (`Services/IntegrationCoordinator.swift` Z. 99 bis 104).
- Antwort nur bei `provider == claude` und `event == PermissionRequest`, bis 300 s (`SessionStore.swift` Z. 1079 bis 1096), Format Claude-Code-Hook-Output (Z. 1257 bis 1295).
- `ProviderSessionKey` (`Models/ProviderSessionKey.swift`): `stableId` ist `"<provider>:<session_id>"` (Z. 23), Parsen trennt am ersten Doppelpunkt (Z. 13). Weitere Doppelpunkte in der Roh-ID sind unproblematisch.

## Sitzungsmodell

- Entstehen: `SessionStore.process` ruft `getOrCreateSession` für jedes Event (`Services/SessionStore.swift` Z. 141, 300 bis 331). `SessionStart` für eine unbekannte Sitzung wird nur als Zeitstempel gemerkt (`Services/NotchiStateMachine.swift` Z. 65 bis 86). Ein `PreToolUse` allein erzeugt eine Sitzung.
- Enden: nur `SessionEnd` (Z. 271 bis 273) oder manuelles Schließen (Z. 440 bis 448). Kein Timeout. Nach 300 s nur `sleeping` (`Models/SessionData.swift` Z. 72, 474 bis 481). Prozess-Liveness nur für Codex.
- Label: `"<projectName> #<n>"`, `projectName` ist die letzte Pfadkomponente von `cwd` (`SessionData.swift` Z. 74 bis 76, `SessionStore.swift` Z. 283 bis 290). Nummern pro Gruppe fortlaufend (Z. 810 bis 830). Eigener Name nur mit `claude_process_id` und passender `~/.claude/sessions/<pid>.json` (Z. 184 bis 186, 382 bis 399; `Services/ClaudeSessionNameReader.swift` Z. 15 bis 26).
- `SubagentStop` (Z. 267 bis 269) wie `Stop`: `clearPendingQuestions()`, `updateTask(.idle)`. Keine Unterscheidung nach `agent_id`.

### Payload für eine Subagenten-Figur

| Feld | Wert |
|---|---|
| `provider` | `claude` |
| `session_id` | `"<eltern-id>:agent:<agent_id>"` |
| `cwd` | `"<eltern-cwd>/<agent_type>"`, letzte Komponente wird Label |
| `event` | `PreToolUse`/`PostToolUse` (working), `SubagentStop` (idle), danach `SessionEnd` (entfernen) |
| `status` | `running_tool`/`processing` bzw. `waiting_for_input` |
| `transcript_path` | leer |
| `interactive` | `false` (keine Töne, kein Dateiwächter, keine Emotionsanalyse; `Services/SoundService.swift` Z. 20 bis 22, `NotchiStateMachine.swift` Z. 112 bis 123) |
| `claude_process_id` | weglassen |

- Notchis eigener Hook schickt Subagenten-Events unter der Eltern-ID. Das Haupt-Maskottchen spiegelt die Agentenarbeit, fällt bei `SubagentStop` kurz auf idle. Bestandsverhalten, von der Mod nicht beeinflussbar.

## Zustandsautomat

Abbildung in `SessionStore.process` (Z. 199 bis 274):

| Event | Task |
|---|---|
| `UserPromptSubmit` | `working` (lokale Slash-Befehle: `idle`, Z. 877 bis 880) |
| `PreCompact` | `compacting` |
| `SessionStart` | `working` nur bei `isProcessing` |
| `PreToolUse` | `working`; bei `AskUserQuestion` `waiting` |
| `PermissionRequest` | `waiting` |
| `PostToolUse` | `working` |
| `Stop`, `SubagentStop` | `idle` |
| `SessionEnd` | entfernen |

- `status` steuert nur `isProcessing` (Z. 926 bis 928), Sortierung (Z. 56 bis 63) und Spinner.
- `sleepDelay` 300 s (`SessionData.swift` Z. 72). `waving` nur Startgruß.
- `spriteFamily`: Eins-zu-eins aus Provider (`Models/NotchiState.swift` Z. 125 bis 136), `NotchiSpriteFamily` geschlossenes Enum (Z. 114 bis 118).
- Namensauflösung (Z. 180 bis 222): `family_task_emotion`, dann `elated` zu `happy` und `sob` zu `sad`, dann `_neutral`, dann dieselbe Kette mit `idle`, zuletzt `family_idle_neutral`. Für `working` zusätzlich `_flipped` (Z. 286 bis 291). Framezahl aus Seitenverhältnis (Z. 318 bis 325), `compacting` 5, `waving` 25 Frames (Z. 83 bis 89).
- Bildquelle ausschließlich Asset-Katalog: `NSImage(named:)` (Z. 161 bis 166), `Image(spriteSheet)` (`Views/Components/SpriteSheetView.swift` Z. 119). Kein Laden aus Dateien.

## Darstellung

- Ausgeklappt: `GrassIslandView` zeigt `sessionStore.sortedSessions`, alle Sitzungen, keine Obergrenze (`NotchContentView.swift` Z. 605 bis 612, `Views/GrassIslandView.swift` Z. 115 bis 126). Position aus Hash der `stableId`, X 0,05 bis 0,95 mit Mindestabstand 0,15, Y-Versatz bis 51 pt (`SessionData.swift` Z. 126 bis 133, 152 bis 154, 176 bis 217).
- Geschlossen: zwei Slots (`NotchSlotContent` in `Core/AppSettings.swift` Z. 129 bis 170: `latest, ring, claude, codex, devin, nothing`), je höchstens ein Sprite (`sessionForSprite`, `NotchContentView.swift` Z. 243 bis 251). `latest` nimmt die aktivste Sitzung, Subagenten verdrängen dort das Haupt-Maskottchen (Folgerung).
- `launchWave`: Startgruß 2,6 s nach 1 s Vorlauf mit Familie aus `lastUsedAgentProvider` (Z. 1004 bis 1036, `NotchiState.swift` Z. 139).

## Hook-Installer

- Läuft bei jedem App-Start (`AppDelegate.swift` Z. 56, 64 bis 68; `IntegrationCoordinator.swift` Z. 44 bis 48) und beim Einschalten in den Einstellungen (Z. 70 bis 80). Keine Versionsprüfung.
- Skriptdatei: `HookFile.writeScriptIfNeeded` (`Services/HookFile.swift` Z. 18 bis 34) überschreibt bei abweichendem Inhalt. Ziel `${CLAUDE_CONFIG_DIR}/hooks/notchi-hook.sh`, Resolver in `Services/ClaudeUsageService.swift` Z. 194 bis 227.
- Upsert (`Services/HookInstaller.swift` Z. 52 bis 122): Marker `cmd.contains("notchi-hook.sh")` (Z. 91). Eigene Einträge werden auf den kanonischen String (Z. 7) zurückgesetzt (Z. 96 bis 98), fehlende Gruppen angehängt (Z. 106 bis 108), fremde Einträge bleiben (Test `Tests/HookInstallerTests.swift` Z. 18 ff.). Schreiben nur bei Byte-Unterschied, ohne Backup, `sortedKeys` und `prettyPrinted` (Z. 132). Deinstallation entfernt nur Marker-Einträge (Z. 228 bis 247).
- Neun Events: `UserPromptSubmit, SessionStart, PreToolUse, PostToolUse, PermissionRequest, PreCompact, Stop, SubagentStop, SessionEnd` (Z. 69 bis 79).

### Varianten

- (a) Eigener Hook-Eintrag mit anderem Skriptnamen: überlebt Neustart, Update, Deinstallation. Tragfähig.
- (b) Notchis Skript ersetzen: wird beim nächsten Start überschrieben. Nicht tragfähig.
- (c) Notchis `command` umbiegen: mit Marker zurückgesetzt, ohne Marker doppelt. Nicht tragfähig.

## Einstellungen und Erweiterungspunkte

- UserDefaults `com.ruban.notchi` (`Core/AppSettings.swift` Z. 230 bis 271): `showSpriteWhenIdle`, `islandBackground`, `showGrassIsland`, `showGitBranchAndPullRequest`, `expandOnHover`, `panelToggleShortcut`, `notchLeftContent`, `notchRightContent`, `expandedPanelScale`, `mainUsageBarPeriod`, `notificationSound*`, `customNotificationSounds`, `isMuted`, `isUsageEnabled`, `emotionAnalysis*`, `lastUsedAgentProvider`, `agentHooksDisabledProviders`. Beobachtet über `UserDefaults.didChangeNotification` (`AppDelegate.swift` Z. 157 bis 166). Nichts für Sprites.
- Umgebung in der App: `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_OAUTH_TOKEN`, `PATH`. Im Skript: `NOTCHI_SOCKET_PATH`, `NOTCHI_INTERACTIVE` (vom Skript selbst gesetzt, Z. 8, 18; `-p`/`--print` in Eltern- oder Großelternprozess, Z. 11 bis 17), `DEVIN_PROJECT_DIR`.
- Keine URL-Schemata, kein Sprite-Ordner, keine Konfigurationsdatei. Application Support: `Notchi/notchi.sock` (HEAD), `Notchi/Sounds/`.
- Einziger äußerer Einfluss auf das Bild: der Socket (Provider, Zustand über Events).
- Fremdfamilien (codex, devin) als Notlösung verworfen: Codex verwirft Sitzungen ohne `transcript_path` (`Services/CodexProviderAdapter.swift` Z. 68 bis 92) und startet Prozess-Monitoring, Devin kennt sechs Events, beide schreiben `lastUsedAgentProvider` um.

## Weg zu eigenen Sprites

Devin-Adapter als Muster für einen vierten Provider: `AgentProvider.swift`, `HookEvent.swift`, `DevinProviderAdapter.swift` (68 Z.), `DevinHookInstaller.swift` (225 Z.), `notchi-devin-hook.sh` (136 Z.), Registrierung in `IntegrationCoordinator.swift` Z. 28, 12 Dateien mit `case .devin`. Zu teuer und semantisch falsch.

Schätzung "Sprite-Familie als freier String plus Laden aus Ordner":

| Datei | Änderung | Zeilen |
|---|---|---|
| `Models/NotchiState.swift` | Familie als String-Wrapper, `probeSpriteSheetImage` zusätzlich `NSImage(contentsOfFile:)` aus `~/Library/Application Support/Notchi/Sprites/<name>.png`, Cache-Key, `targetFPS` | 40 bis 60 |
| `Views/Components/SpriteSheetView.swift` | `Image(nsImage:)` mit Lookup (Z. 119) | 10 bis 20 |
| `Models/HookEvent.swift` | Feld `sprite_family` oder `agent_type` | 10 bis 15 |
| `Models/SessionData.swift` | gespeicherte Familie statt `provider.spriteFamily` (Z. 38) | 10 |
| `Services/SessionStore.swift` | Familie aus Event übernehmen | 5 |
| `Services/ClaudeProviderAdapter.swift` | durchreichen | 3 |
| `NotchContentView.swift` | `contentAcceptsSprite`, `launchWave` auf String | 10 |
| `Resources/notchi-hook.sh` | `agent_type`/`agent_id` durchreichen | 10 bis 20 |
| Tests | Ergänzungen | 40 bis 80 |

Summe etwa 140 bis 220 Zeilen in 8 bis 9 Quelldateien plus Tests. Weg: Issue, dann Pull Request (CONTRIBUTING.md verlangt das Issue vorab).

## Belegte Hook-Felder (Test 17.10.2026, Claude Code 2.1.296)

Siehe `tests/hooklog/README.md`. Subagenten-Events tragen Eltern-`session_id` und Eltern-`transcript_path`, zusätzlich `agent_id` und `agent_type`; eingerahmt von `SubagentStart` und `SubagentStop`.

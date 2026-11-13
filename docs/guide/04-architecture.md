# 04 · Architecture

> **En bref**
> Un seul fil, « moteur », fait tourner la boucle `Engine` et possède `Core` (la machine à états).
> Tous les autres fils (micro, Whisper, bot, interface Qt) lui parlent par des **files** (`queue`).
> Règle d'or : **jamais modifier `Core` depuis un autre fil.**

## Modules et dépendances

```mermaid
graph TD
    MAIN["__main__.py"] --> APP["app.py<br/>main() + Engine"]
    APP --> CORE["core.py<br/>Core, tables de commandes"]
    APP --> CAM["camera.py"]
    APP --> HANDT["hand.py<br/>HandTracker"]
    APP --> VOICE["voice.py<br/>Vosk"]
    APP --> ASK["ask.py<br/>Whisper + Haiku"]
    APP --> TYPER["typer.py"]
    APP --> APPS["apps.py"]
    APP --> REM["reminders.py<br/>Desk"]
    APP --> DL["discord_link.py"]
    APP --> UI["ui.py<br/>fenêtres Qt"]
    APP --> OVL["overlay.py<br/>dessin aperçu"]
    APP --> OUT["output.py<br/>SendInput"]
    APP --> GARDE["garde.py<br/>battement"]
    APP --> SMALL["power.py, fenetre.py, aide.py,<br/>volume.py, sounds.py,<br/>speech.py, vscode.py,<br/>audio_repair.py, stats.py"]
    CORE --> GEST["gestures.py"]
    CORE --> HEAD["head.py"]
    CORE --> POSES["poses.py"]
    CORE --> FILT["filters.py<br/>One Euro"]
    CORE --> HANDF["hand.py<br/>compute_features"]
    CORE --> CALV["calendar_view.py<br/>mots du calendrier"]
    VOICE -. "CHROME_KEYS" .-> CORE
    REM --> TIM["timers.py"]
    REM --> CALV
    DL --> DK["discord_keys.py"]
    DK --> LDB["leveldb_mini.py"]
    TYPER --> ASK
    APP --> CFG["config.py"]
```

> **Note** `core.py` ne dépend d'aucun service extérieur : il prend des points et des mots, il rend une liste d'**actions** (tuples comme `("click", "left")`). C'est ce qui le rend testable sans caméra.

## Fils d'exécution et files

```mermaid
flowchart LR
    subgraph QT["Fil principal : Qt (ui.py)"]
        WINS["Accueil, verre,<br/>STOP, œil, réparation"]
    end
    subgraph MOT["Fil moteur : Engine"]
        ENG["Engine.tick()"] --> CORE["Core"]
    end
    CAMF["Fil caméra<br/>dernière image"] -->|"cam.read()"| ENG
    VOX["Fil voice<br/>micro + Vosk"] -->|"file events"| ENG
    WORK["Fils Whisper / Haiku<br/>ask, typer, Desk, apps"] -->|"files de résultats"| ENG
    BOTF["Fil pont-bot<br/>socket local"] -->|"bot.inbox"| ENG
    WINS -->|"pointer_requests,<br/>app_messages"| ENG
    ENG -->|"signaux Qt (Bridge)"| WINS
    BEAT["Fil battement"] -->|"logs/battement.json"| GARDE["Processus gardien"]
    SURV["Fil surveillance"] -->|"logs/blocage.txt"| LOG[("logs/")]
    WINS -->|"STOP : stop.set()"| ENG
```

| Fil | Rôle | Parle au moteur par |
|---|---|---|
| Qt (principal) | fenêtres, boutons | `pointer_requests`, `app_messages` ; reçoit `Bridge` (signaux) |
| `moteur` | `Engine.run()`, seul à toucher `Core` | — |
| caméra | lit la webcam, garde la dernière image | `cam.read(seq)` |
| `voice` | micro, Vosk, 2e avis, capture audio | `listener.events` (lu par `poll()`) |
| Whisper / Haiku | transcription, questions, rappels, applis | files internes de chaque service, lues dans la boucle |
| `pont-bot` | socket vers le bot Discord | `bot.inbox` (vidée par `bot_events`) |
| `battement` | écrit `battement.json` toutes les 2 s | lit `live["beat"]` |
| `surveillance` | boucle muette plus de 10 s : pile des fils dans `blocage.txt` | lit `live["beat"]` |

> **Note** Le lancement d'un travail lent (Whisper, Haiku, volume, réparation du son) se fait toujours dans un fil à part. La boucle ne fait jamais d'appel bloquant.

## La boucle `Engine` en 5 étapes

`Engine.tick()` (dans `app.py`) fait un tour : **détecter, fond, écouter, faire, montrer**.

```mermaid
flowchart TD
    T["tick(t)<br/>live beat = t"] --> D["1. detect<br/>image, MediaPipe main ou visage<br/>Core.step / step_head"]
    D --> B["2. background<br/>ticks dictée, question, type, ouvre<br/>files Qt, mode Chrome, bot, Desk"]
    B --> L["3. listen<br/>listener.poll()<br/>Core.voice(mot) + sons"]
    L --> R["4. resolve + execute<br/>chaque service prend ses actions<br/>ctl.execute : SendInput"]
    R --> A["after : sons, journal"]
    A --> P["5. publish<br/>aperçu + état du verre (Bridge)"]
    P --> T
    D -. "erreur" .-> X["exception notée, release_all,<br/>on continue"]
    X --> T
```

- `resolve` enchaîne : `question_actions`, `type_actions`, `open_actions`, `desk.actions`, `discord_actions`, `power_actions`, `window_actions`, `vscode_actions`. Chacun **retire** les actions qu'il traite et rend le reste.
- La détection est plafonnée à 20 images/s, ralentie sans main, arrêtée en DÉSACTIVÉ.
- 20 erreurs en moins de 10 s : la boucle abandonne (le gardien relance).

## Cycle de vie

```mermaid
sequenceDiagram
    participant W as Windows (Démarrage)
    participant G as Gardien (garde.py)
    participant I as Iris (app.py)
    participant B as Bot Discord
    W->>G: pythonw -m motionzero.garde --start
    G->>I: lance pythonw -m motionzero --voice
    I->>I: config, Core, caméra, Vosk, Qt
    loop toutes les 2 s
        I->>G: logs/battement.json (pid, âge de la boucle)
    end
    loop toutes les 3 s
        G->>G: decide : rien, relance ou tue
    end
    alt plus de battement 20 s, ou boucle figée 60 s
        G->>I: taskkill /F /PID (jamais /T)
        G->>I: relance
    else STOP
        I->>G: écrit logs/arret_voulu
        I->>B: bye
        Note over G: ne relance pas
    end
```

- **Démarrage** (`main()`) : journal tournant, config, `Core`, poses calibrées, caméra, MediaPipe, voix (si `--voice`), services, fenêtres Qt, puis les fils moteur, battement et surveillance.
- **Gardien** : 3 relances en 180 s au plus, sinon il abandonne (écrit dans `garde.log`). Il vérifie qu'aucune Iris ne tourne déjà (le bot relance aussi).
- **Arrêt** : `stop.set()`, tout relâché, `worker.join(3 s)`, puis `os._exit(0)` pour ne laisser aucun fil vivant.

---
[← Commandes vocales](03-commandes-vocales.md) · [Sommaire](README.md) · [Structure du projet →](05-structure-du-projet.md)

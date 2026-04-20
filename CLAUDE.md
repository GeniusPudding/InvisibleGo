# InvisibleGo

A turn-based combat game built on top of 9x9 Go rules, where **players cannot see each other's stones**. Each side plays on a full 9x9 board but only sees their own stones (plus empty points left by captures). Captures, suicide, and ko are enforced exactly like standard Go — but the opponent's position is hidden.

This is **not** a Go client. It reuses Go's move mechanics as the substrate for a hidden-information game. Engines like KataGo (https://github.com/lightvector/katago) are technical reference only; the standard GTP protocol assumes full information and is **not** suitable here.

## Game rules

### Board
- 9x9 grid
- Black plays first (standard Go convention)

### Move mechanics (identical to Go)
A move is **illegal** if any of the following holds:
- The point is occupied by an opponent's stone *(but the player cannot distinguish this from other illegal cases)*
- The point is occupied by the player's own stone
- The move would be suicide (own group ends with zero liberties, unless it captures first)
- The move violates the ko rule (recreates the immediately previous board position)

Captures: after placing a stone, remove every opponent group with zero liberties. Then check suicide on the placed group.

### Visibility rules (the twist)
- Each player sees **only** their own stones plus empty points
- The opponent's stones are invisible
- When the player's own stones are captured, they disappear from the player's view. The player is told **how many** stones they just lost, but not by which move
- When a player captures opponent stones, they are told **how many** stones they captured. The captured stones were never visible and remain so

### Turn structure — 3-attempt rule
- On each turn the player may attempt up to **3 moves**
- Every illegal attempt returns a generic `ILLEGAL` response with **no** reason field — opponent-occupied, own-occupied, suicide, and ko all look identical from the client side
- If all 3 attempts are illegal, the turn is auto-skipped (equivalent to a pass)
- A legal move ends the turn immediately
- Rationale: prevents "click scanning" — probing every point to map the opponent's board. An attacker would spend 3 attempts per turn to check 3 points; auto-skip makes scanning cost full turns

### End of game
- Two consecutive passes (either voluntary or auto-skipped) end the game
- The full board is revealed to both players
- **Chinese area scoring** (數子法): own stones on the board + empty points surrounded only by own stones. Higher score wins

## Architecture

Three decoupled layers. The core engine is transport-agnostic and drives CLI, LAN, and web frontends without modification.

```
core/       Pure rules engine. No I/O, no networking, no UI.
            - Board state, move validation, capture, ko tracking
            - Per-player view derivation
            - Turn state machine (attempts_left: 0..3)
            - Chinese area scoring

protocol/   JSON message schemas shared across all transports.
            client -> server:  play(x,y) | pass | resign
            server -> client:  result(ok|illegal, captured_count?)
                               opponent_moved(your_losses)
                               turn_skipped
                               game_end(revealed_board, score)

transport/  Pluggable transport.
            - lan:  stdlib asyncio TCP, length-prefixed JSON frames
            - web:  FastAPI + WebSocket, same JSON schemas

frontend/   Clients that speak the protocol.
            - cli:     terminal-based, for rule verification
            - desktop: GUI (library TBD)
            - web:     browser UI (framework TBD)
```

**Hard invariant: never leak opponent information.** The core engine is the single source of truth for what each player may see. Any transport or UI that needs board state must call `core.view(player_id)` — never read raw board arrays. This invariant is enforced by code review and by tests that assert illegal-move responses are byte-identical across all four illegal reasons.

## Tech stack

- **Language**: Python 3.11+
- **Core engine**: pure stdlib, no dependencies
- **Tests**: pytest
- **LAN server**: stdlib `asyncio` TCP
- **Web server**: FastAPI + WebSockets
- **GUI**: deferred — evaluate after CLI works

Rationale: Python is fast enough for 9x9 rule logic, integrates cleanly with future AI opponents (KataGo bindings, PyTorch custom models), and keeps prototype velocity high.

## Development order

Build in layers, each independently verifiable. Do not move to step N+1 until step N has passing tests and a working manual run.

1. **`core/`** — rules engine + unit tests. Board, captures, ko, 3-attempt turns, view derivation, area scoring. No networking, no UI.  *(done)*
2. **`frontend/cli.py`** — single-process hotseat for two players on one terminal. Validates rules end-to-end with human play.  *(done)*
3. **`transport/lan/`** — TCP server + client speaking the protocol; reuses `transport/session.py` for orchestration.  *(done)*
4. **`transport/web/` + `frontend/web/`** — FastAPI + WebSocket server reusing the same `GameSession`; browser SVG UI.  *(done)*
5. **`frontend/desktop/`** — PySide6 GUI client. Same LAN protocol underneath (via `qasync`-integrated `NetworkClient`). Packable to a single executable with PyInstaller.  *(done)*
6. **AI opponent** — optional later addition.

## Running

Install (web extras optional):

```
pip install -e .[web,test]
```

Hotseat (two players on one terminal):

```
python -m frontend.cli
```

LAN (TCP, separate machines or terminals):

```
# host
python -m transport.lan.server --host 0.0.0.0 --port 5555
# each player
python -m transport.lan.client --host <server-ip> --port 5555
```

Web (browser):

```
uvicorn transport.web.server:app --host 0.0.0.0 --port 8000
# open http://localhost:8000/ in two browser windows
```

Desktop (PySide6 GUI):

```
# host side (starts a local server + client in one process)
python -m frontend.desktop --host 0.0.0.0 --port 5555 --serve
# joining side (another machine or process)
python -m frontend.desktop --host <host-ip> --port 5555
# or just run it and use the connect dialog
python -m frontend.desktop
```

Known compat note: PySide6 6.11 has a DLL-loader issue on some Windows
Python builds ("specified procedure not found"). `pip install PySide6==6.7.3`
is a stable working baseline on Anaconda Python 3.12 / Windows.

Tests:

```
QT_QPA_PLATFORM=offscreen pytest   # offscreen needed for desktop tests
```

## Deployment (Linux VM + Caddy)

Server-side deployment lives in `deploy/`:

```
deploy/
├── invisiblego.service   systemd unit: runs uvicorn as invisiblego user on :8000
├── Caddyfile             Caddy reverse proxy + automatic Let's Encrypt TLS
└── setup.sh              one-shot installer for Ubuntu 22.04/24.04
```

On a fresh Ubuntu VM (AWS EC2, Oracle Cloud, Contabo, etc.):

```
git clone <repo-url> ~/InvisibleGo && cd ~/InvisibleGo
sudo bash deploy/setup.sh
```

The installer creates a `/opt/invisiblego` directory with its own venv and
a dedicated `invisiblego` system user, installs Caddy, enables both as
systemd services, and binds uvicorn to 127.0.0.1:8000 so only Caddy can
reach it. Edit `/etc/caddy/Caddyfile` to set your domain, then
`systemctl reload caddy` for auto-TLS.

Firewall: open 80 (for ACME + HTTP redirect) and 443 (HTTPS) in the cloud
provider's security group. SSH (22) only from trusted IPs.

## Packaging (PyInstaller)

Build a standalone executable from the desktop client. PyInstaller does
not cross-compile, so run the command on each target OS (Windows → .exe,
macOS → .app, Linux → ELF). A GitHub Actions matrix with Windows / macOS /
Linux runners is the standard CI pattern for distribution.

```
pip install -e .[desktop,build]
pyinstaller InvisibleGo.spec
# output lands in dist/InvisibleGo[.exe]
```

The spec excludes web-only deps (FastAPI / uvicorn / websockets) and test
deps so the resulting binary stays lean. Expected size ~80–150 MB on
Windows (dominated by Qt DLLs).

## Conventions

- **Language in repo**: English for all code, comments, docstrings, commit messages, and Markdown. Chat may be in Traditional Chinese; repo artifacts stay English.
- **Illegal responses must be indistinguishable**. The `ILLEGAL` message carries no field revealing *why* the move was illegal. Enforced at the protocol schema level (no `reason` field exists).
- **`core/` has no I/O**. If you reach for `print`, `input`, `open`, `socket`, or `requests` inside `core/`, stop — that belongs in a frontend or transport.
- **Tests first for rules code**. Go edge cases (ko, multi-stone captures, suicide-that-actually-captures, self-atari) are easy to get wrong. Every rule clause gets a dedicated test.
- **No premature GUI work**. The CLI frontend is the validation harness for the rules engine. GUI work begins only after LAN play is solid.

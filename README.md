# InvisibleGo

A turn-based combat game built on top of 9x9 Go, where **players cannot
see each other's stones**. Each side plays on a full 9x9 board but sees
only its own stones (plus points left empty by captures). Captures,
suicide, and ko are enforced exactly like standard Go — but the
opponent's position is hidden.

Every illegal move, whatever the reason (opponent-occupied, own-occupied,
suicide, ko), returns a single generic `ILLEGAL` response with no reason
field. Each turn grants at most **3 attempts**; if all three fail the
turn auto-skips. Two consecutive passes (voluntary or auto) end the game
and trigger **Chinese area scoring** (數子法) on the revealed board.

Full spec — board semantics, visibility rules, 3-attempt turn machine,
architecture invariants — lives in [`CLAUDE.md`](CLAUDE.md).

## Repo layout

```
core/       Pure rules engine (board, captures, ko, scoring, view). No I/O.
protocol/   Shared JSON message schemas for every transport.
transport/  Pluggable transports:
              session.py     — transport-agnostic GameSession orchestrator
              lan/           — stdlib asyncio TCP, length-prefixed JSON
              web/           — FastAPI + WebSocket + matchmaker (rooms)
frontend/   Clients that speak the protocol:
              cli.py         — single-process hotseat
              desktop/       — PySide6 GUI (LAN protocol under the hood)
              web/           — browser SVG UI (served by transport/web)
tests/      pytest suite (rules, protocol, session, full games, matchmaker).
deploy/     One-shot systemd + Caddy install for a fresh Ubuntu VM.
```

## Install

Requires Python 3.11+.

```bash
# Core + CLI only (no extras)
pip install -e .

# With web server (FastAPI / uvicorn / websockets)
pip install -e .[web]

# With desktop GUI (PySide6) — see version note below
pip install -e .[desktop]

# For running tests
pip install -e .[test]
```

PySide6 version note: on Windows + Anaconda Python 3.12, PySide6 6.11
has a DLL-loader failure ("specified procedure not found"). Pin to
`PySide6==6.7.3` as a stable baseline.

## Single-machine play

### CLI hotseat — two players sharing one terminal

```bash
python -m frontend.cli
```

Fastest way to verify the rules engine end-to-end. No networking.

### Desktop (PySide6) — two processes on one machine

Terminal A (host also plays as one side):

```bash
python -m frontend.desktop --host 127.0.0.1 --port 5555 --serve
```

Terminal B (the other side):

```bash
python -m frontend.desktop --host 127.0.0.1 --port 5555
```

Or run without flags and use the in-app connect dialog:

```bash
python -m frontend.desktop
```

### LAN (terminal client) — two processes on one machine

```bash
# terminal A
python -m transport.lan.server --host 127.0.0.1 --port 5555
# terminal B and C
python -m transport.lan.client --host 127.0.0.1 --port 5555
```

### Web — browser UI

```bash
uvicorn transport.web.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/ in two browser windows
```

The web server includes a matchmaker: each client can either `create`
a room (gets a 4-character code) or `join` by code, or request
`random` pairing.

## Tests

The whole suite uses `pytest`. Desktop tests need a Qt platform; set
`QT_QPA_PLATFORM=offscreen` (Linux / CI) or run on a machine with a
real display.

```bash
# Everything
QT_QPA_PLATFORM=offscreen pytest

# Just the rules / session layer
pytest tests/test_board.py tests/test_game.py tests/test_scoring.py tests/test_session.py

# Full-game integration tests (scripted games played to scoring)
pytest tests/test_full_game.py

# Visual mode — prints the final referee board + both player views +
# score breakdown for every game, so you can eyeball endgames without
# clicking through two GUIs:
pytest tests/test_full_game.py -s
```

`tests/test_full_game.py` scripts six end-to-end games via the
transport-agnostic `GameSession` (territory split, corner capture,
ko attempt + resolution, auto-skip into double pass, resign mid-game,
symmetric tie) and asserts on the final `game_end` payload.

## Deployment (VM)

`deploy/setup.sh` is a one-shot installer for a fresh Ubuntu 22.04 /
24.04 host (AWS EC2, Oracle Cloud, Contabo, etc.). It creates a
dedicated system user, installs the web extras in `/opt/invisiblego`,
installs Caddy for auto-TLS, and enables both as systemd services.

```bash
git clone https://github.com/GeniusPudding/InvisibleGo.git ~/InvisibleGo
cd ~/InvisibleGo
sudo bash deploy/setup.sh
# edit /etc/caddy/Caddyfile to point at your domain, then:
sudo systemctl reload caddy
```

Open ports 80 and 443 at the cloud provider's firewall; SSH only from
trusted IPs.

## Packaging (desktop standalone)

```bash
pip install -e .[desktop,build]
pyinstaller InvisibleGo.spec
# output lands in dist/InvisibleGo[.exe]
```

PyInstaller does not cross-compile — run once per target OS.

## Roadmap

- [x] `core/` — rules engine + unit tests
- [x] `frontend/cli.py` — hotseat on one terminal
- [x] `transport/lan/` — TCP server + client
- [x] `transport/web/` + `frontend/web/` — FastAPI + WebSocket + browser UI
- [x] `frontend/desktop/` — PySide6 GUI client
- [x] Matchmaker (room codes + random pairing) in `transport/web/`
- [ ] **P2P connectivity** — direct peer-to-peer play without a central
      server. Candidates under evaluation:
      - WebRTC data channels with a minimal signaling relay (so the
        matchmaker still arranges introductions but gameplay traffic
        goes peer-to-peer)
      - libp2p / hole punching for a fully decentralized mode
      - The existing LAN TCP transport already handles direct
        peer-to-peer on a trusted network; P2P work extends it across
        NATs
- [ ] AI opponent (KataGo-adjacent or custom; must respect the
      hidden-information handicap — no access to the opponent's board)

## Conventions

- **English** for all code, comments, docstrings, commit messages, and
  Markdown. Chat may be in any language; repo artifacts stay English.
- **`core/` has no I/O.** If you reach for `print` / `input` / `open` /
  `socket` inside `core/`, it belongs in a frontend or transport.
- **Illegal responses are indistinguishable.** The protocol schema has
  no `reason` field, and tests assert byte-identical `ILLEGAL` payloads
  across all four rejection causes — this is a load-bearing invariant
  of the hidden-information design.

See [`CLAUDE.md`](CLAUDE.md) for the complete specification, including
detailed rules, architecture invariants, and the development order.

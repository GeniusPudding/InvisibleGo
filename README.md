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
deploy/     Deployment configs:
              Caddyfile         — reverse proxy + Let's Encrypt TLS
              setup-docker.sh   — install Docker on a fresh Ubuntu VM
              aws-provision.*   — AWS EC2 one-command provisioning (bash + ps1)
              invisiblego.service, setup.sh — legacy systemd path (alternative)
Dockerfile, docker-compose.yml, docker-compose.dev.yml — container stack
```

## Tech stack

| Layer | Tools |
|-------|-------|
| Core rules engine | Pure Python 3.12 (stdlib only) |
| Web server | FastAPI + `uvicorn[standard]` + WebSockets |
| Web frontend | Vanilla HTML / CSS / JS, SVG board |
| Desktop GUI | PySide6 (Qt 6) — threaded blocking socket client |
| LAN / CLI | Python stdlib (`asyncio`, `socket`) |
| Tests | `pytest` + `pytest-asyncio` |
| Container / orchestration | Docker + Docker Compose |
| TLS / reverse proxy | Caddy (auto Let's Encrypt) |
| Desktop packaging | PyInstaller |
| Cloud provisioning | AWS CLI scripts (bash + PowerShell) |

All four client types (CLI, LAN, web, desktop) speak the **same JSON
protocol** against the same `GameSession`. Adding another frontend —
iOS app, Android app, Flutter, React Native, Discord bot — is a new
client that connects to the same WebSocket endpoint. **Zero server
changes** needed per new platform.

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

### Web — browser UI (direct Python)

```bash
uvicorn transport.web.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/ in two browser windows
```

### Web — browser UI (Docker, mirrors production)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# http://localhost:8000
```

The dev overlay exposes `:8000` directly and skips Caddy. In production
the same `docker-compose.yml` brings up Caddy with auto-TLS on `:443`.

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

## Deployment (Docker, primary path)

The production stack is `docker-compose.yml` at the repo root: one
container for the Python + WebSocket server, one container for Caddy
terminating TLS and reverse-proxying to it.

On a fresh Ubuntu 22.04 / 24.04 VM (AWS EC2, Oracle Cloud, Contabo, …):

```bash
git clone https://github.com/GeniusPudding/InvisibleGo.git ~/InvisibleGo
cd ~/InvisibleGo
sudo bash deploy/setup-docker.sh     # installs Docker + brings the stack up
# edit deploy/Caddyfile to set your domain, then:
docker compose restart caddy
```

Redeploy after `git pull`:
```bash
docker compose up -d --build
```

TLS state (ACME account, issued certs) lives in the `caddy_data` named
volume and survives `docker compose down`/`up`.

Multi-service expansion (add an API, bot, or second game on the same
VM):
1. Add a new `services:` entry to `docker-compose.yml`
2. Add a subdomain block to `deploy/Caddyfile`
3. `docker compose up -d && docker compose restart caddy`

Caddy handles TLS for every new subdomain automatically.

### Legacy path (systemd + venv + Caddy on host)

`deploy/setup.sh` keeps the non-Docker install working on a fresh
Ubuntu host (creates a dedicated system user, `/opt/invisiblego` venv,
systemd unit, host-level Caddy). Use this if Docker is a dealbreaker
on the target host. Both paths expose the same protocol.

### AWS EC2 provisioning

One command builds the VM, key pair, security group, and Elastic IP:

```bash
# macOS / Linux / Git Bash:
bash deploy/aws-provision.sh

# Windows PowerShell:
powershell -ExecutionPolicy Bypass -File .\deploy\aws-provision.ps1
```

Requires `aws configure` to have run previously. Idempotent: re-running
detects existing resources by name.

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
- [ ] **Online lobby** — player list, direct challenges, ratings.
      Architecture stays hub-and-spoke through the matchmaker (same
      model as OGS / KGS); hidden-information rules rule out truly
      trustless P2P for strangers. LAN / friend-hosted direct play is
      already supported via `transport/lan/`.
- [ ] **Mobile clients** — iOS / Android / Flutter apps consuming the
      same WebSocket protocol. No server changes required.
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

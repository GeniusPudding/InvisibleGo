# Developing InvisibleGo

Runbook for people who want to read the code, run it locally, run the
tests, or deploy their own instance.

For the player-facing intro see [README.md](README.md). For the full
project specification, architecture invariants, and design rationale see
[CLAUDE.md](CLAUDE.md).

## Technology

Single-source list of every moving part. **Update this table whenever a
dependency, API, or tool is added or dropped** — it's meant to be the
definitive snapshot of "what's actually in the stack right now".

| Layer | Tools |
|-------|-------|
| Language | Python 3.12 (3.11+ minimum) |
| Core rules engine | Pure stdlib — no runtime dependencies |
| Web server | FastAPI + `uvicorn[standard]` + WebSockets |
| Web frontend | Vanilla HTML / CSS / JS, SVG board, Web Audio API (turn chime + countdown tick) |
| Desktop GUI | PySide6 (Qt 6) — threaded blocking socket client, `QApplication.beep()` for turn cue |
| LAN transport | stdlib `asyncio` + length-prefixed JSON frames |
| CLI client | stdlib `asyncio` + blocking `input` |
| Tests | `pytest` + `pytest-asyncio`; SVG endgame snapshots dropped to `tests/snapshots/` per scripted full-game test |
| Container / orchestration | Docker + Docker Compose |
| TLS / reverse proxy | Caddy (auto Let's Encrypt) |
| Desktop packaging | PyInstaller (per-OS, no cross-compile) |
| Cloud provisioning | AWS CLI scripts (bash + PowerShell), t3.micro EC2 + Elastic IP |
| Cost monitoring | `scripts/aws-cost.sh` (`aws ce`, `aws ec2 describe-*`) |

## Repo layout

```
core/          Pure rules engine (board, captures, ko, scoring, view). No I/O.
protocol/      Shared JSON message schemas.
transport/
  session.py   Transport-agnostic GameSession orchestrator.
  lan/         stdlib asyncio TCP, length-prefixed JSON.
  web/         FastAPI + WebSocket + matchmaker (random + room codes).
frontend/
  cli.py       Single-process hotseat.
  desktop/     PySide6 GUI.
  web/         Browser SVG UI (served by transport/web).
tests/         pytest suite.
deploy/
  Caddyfile        Reverse-proxy + auto-TLS config.
  setup-docker.sh  One-shot installer for a fresh Ubuntu VM.
  aws-provision.*  AWS EC2 one-command provisioning (bash + ps1).
  setup.sh + invisiblego.service   Legacy systemd path (alternative).
scripts/       Local dev helpers (e.g., dev-up.ps1 / dev-up.sh).
Dockerfile, docker-compose.yml, docker-compose.dev.yml
InvisibleGo.spec   PyInstaller spec for the desktop build.
```

## Developer workflow

Five surfaces you might edit — each has a distinct refresh path:

| Surface | Files | How to pick up the change |
|---------|-------|---------------------------|
| Python backend | `core/`, `protocol/`, `transport/` | Direct Python: `uvicorn --reload` auto-restarts on save (~1 s). Docker path: `docker compose up -d --build`. |
| Web frontend | `frontend/web/*.{html,css,js}` | FastAPI serves static files from disk — **no server restart needed**. Hard-refresh the browser (Ctrl-F5) to bust the HTTP cache. Docker path still needs `--build` to bake new files into the image. |
| Caddy proxy | `deploy/Caddyfile` | `docker compose restart caddy`. The file is mounted as a volume, no image rebuild. |
| Docker infra | `Dockerfile`, `docker-compose*.yml`, `pyproject.toml` | `docker compose up -d --build`. |
| Desktop GUI | `frontend/desktop/` | Re-run `python -m frontend.desktop`; it's a standalone process, no dev server. |

## Run locally

Pick one of two paths. Both serve the browser UI at `http://localhost:8000`.

### Path A — Direct Python (fastest inner loop)

```bash
pip install -e '.[web]'
uvicorn transport.web.server:app --reload --host 127.0.0.1 --port 8000
```

`--reload` watches every `.py` file. Edit Python → uvicorn restarts in
~1 s. Edit HTML/CSS/JS → no server restart; just Ctrl-F5 the browser.

Open `http://localhost:8000/` in two browser tabs (or an incognito
window as the second client) and play a full game in ~30 s.

### Path B — Docker compose (mirrors production)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# → http://localhost:8000
```

The `dev.yml` overlay exposes `:8000` on the host and skips Caddy/TLS.
After any code change, from another terminal:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Rebuilds the image and swaps the container in ~5 s — the `pip install`
layer is cached unless `pyproject.toml` changed, so only the COPY + user
setup layers rerun. Follow logs:

```bash
docker compose logs -f invisiblego
```

Helper that also prints every LAN URL (so phones / laptops on the same
Wi-Fi can connect) and then starts the stack:

```powershell
.\scripts\dev-up.ps1            # Windows PowerShell
```
```bash
bash scripts/dev-up.sh          # macOS / Linux / Git Bash
```

### Other clients

```bash
python -m frontend.cli              # hotseat on one terminal, no networking
python -m frontend.desktop          # PySide6 GUI with connect dialog
python -m transport.lan.server      # standalone LAN TCP server, port 5555
python -m transport.lan.client      # LAN TCP client
```

Two desktop processes on one machine — first one embeds the server,
second joins:

```bash
python -m frontend.desktop --host 127.0.0.1 --port 5555 --serve
python -m frontend.desktop --host 127.0.0.1 --port 5555
```

## Tests

```bash
pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen pytest
```

Desktop widget tests need a Qt platform; `offscreen` avoids a display.
`tests/test_full_game.py -s` prints final boards + both player views +
score breakdown for scripted end-to-end games.

## Deploy to a fresh cloud VM

`deploy/aws-provision.*` builds an AWS EC2 t3.micro in Tokyo with key
pair, security group, and Elastic IP — one command, idempotent:

```bash
bash deploy/aws-provision.sh                                              # macOS / Linux / Git Bash
powershell -ExecutionPolicy Bypass -File .\deploy\aws-provision.ps1       # Windows
```

Requires `aws configure` already set. Then SSH into the VM it prints
and:

```bash
git clone https://github.com/GeniusPudding/InvisibleGo.git
cd InvisibleGo
sudo bash deploy/setup-docker.sh     # installs Docker + brings the stack up
```

Point a DNS A record at the Elastic IP, put the domain in
`deploy/Caddyfile` (replacing the placeholder), and
`sudo docker compose restart caddy`. Caddy obtains a Let's Encrypt cert
automatically on the first HTTPS request.

## Day-to-day operations

Run on the VM (prefix with `sudo` if not in the `docker` group yet):

```bash
# Status + logs
docker compose ps
docker compose logs -f invisiblego         # app logs
docker compose logs -f caddy               # TLS / reverse-proxy logs

# Edited deploy/Caddyfile → pick it up
docker compose restart caddy

# Deployed new code? (pull then rebuild + recreate)
git pull
docker compose up -d --build

# Stop / start the whole stack (containers only, volumes preserved)
docker compose stop
docker compose start

# Full teardown (drops containers, keeps TLS certs in named volume)
docker compose down
docker compose down --volumes    # also drops certs; will re-issue on next up
```

Run locally (toggle EC2 compute billing; EBS + Elastic IP still
cost a couple USD/month):

```bash
aws ec2 stop-instances  --instance-ids <id> --region ap-northeast-1
aws ec2 start-instances --instance-ids <id> --region ap-northeast-1
```

Tear down entirely (stop billing for good):

```bash
aws ec2 terminate-instances --instance-ids <id> --region ap-northeast-1
aws ec2 release-address --allocation-id <eip-alloc-id> --region ap-northeast-1
```

## Common pitfalls

- **Caddy crash-looping** → check `docker compose logs caddy`. Usually
  a Caddyfile syntax error (braces on wrong lines) or a domain whose
  DNS hasn't propagated yet.
- **`ERR_CONNECTION_REFUSED` on the public URL** → verify AWS Security
  Group has ports 80 / 443 open, and Caddy container is `Up` (not
  `Restarting`).
- **SSH refused from a new network** → Security Group's port 22 rule
  whitelists only the IP you provisioned from. Add your current IP:
  ```bash
  aws ec2 authorize-security-group-ingress --group-name invisiblego-sg \
    --protocol tcp --port 22 --cidr "$(curl -s https://checkip.amazonaws.com)/32" \
    --region ap-northeast-1
  ```
- **`docker` permission denied on first SSH after install** → you need a
  new shell after being added to the `docker` group. Quick fix:
  `newgrp docker`, or just prefix with `sudo`.

## Package the desktop client as a `.exe`

```bash
pip install -e '.[desktop,build]'
pyinstaller InvisibleGo.spec
# dist/InvisibleGo.exe
```

PyInstaller does not cross-compile — build once per target OS (Windows
→ `.exe`, macOS → `.app`, Linux → ELF). GitHub Actions matrix with
Windows / macOS / Linux runners is the standard CI pattern.

Known compat note: on Windows + Anaconda Python 3.12, PySide6 **6.11**
has a DLL-loader failure ("specified procedure not found"). Pin to
`PySide6==6.7.3`.

## Conventions

- **English** for all code, comments, docstrings, commit messages, and
  Markdown. Chat can be any language; repo artifacts stay English.
- **`core/` has no I/O.** If you reach for `print` / `input` / `open` /
  `socket` inside `core/`, it belongs in a frontend or transport.
- **Illegal responses are indistinguishable.** The protocol schema has
  no `reason` field, and tests assert byte-identical `ILLEGAL` payloads
  across all four rejection causes — load-bearing invariant of the
  hidden-information design.
- **Keep the two top-level docs accurate every commit.** README.md is
  the player-facing dashboard; DEVELOPER.md (this file) is the dev +
  ops runbook. Every change that lands on `main` should leave the
  matching section current:
  - New / dropped dependency or tool → [Technology](#technology) table (this file)
  - Changed edit-loop for some file → [Developer workflow](#developer-workflow) table (this file)
  - New runbook command → [Day-to-day operations](#day-to-day-operations) (this file)
  - New deployment step → [Deploy to a fresh cloud VM](#deploy-to-a-fresh-cloud-vm) (this file)
  - New operational footgun → [Common pitfalls](#common-pitfalls) (this file)
  - New user-visible feature → `Why it's interesting`, `Roadmap` in README.md

  Stale sections compound fast and erode trust in the rest of the doc.

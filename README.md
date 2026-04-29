# InvisibleGo

A fog-of-war 9×9 Go variant. You see only your own stones, and every
illegal move looks identical — a blocked point, a ko, and a suicide all
return the same generic reject. Nobody ever sees the whole board except
the server.

## Play now

**→ [invisiblego.puddings-world.com](https://invisiblego.puddings-world.com/)**

No installation. Works on any browser, desktop or mobile.

1. Open the URL, type a name
2. Click **Find random opponent** to be paired with a stranger, or
   **Create private room** to get a 4-character code to share with a
   friend (they pick **Join room** and paste the code)
3. Take turns clicking intersections. You have **20 seconds** and up to
   **3 attempts** per turn — illegal moves (on an opponent stone, your
   own, a suicide, or a ko) all look identical, so single-point scanning
   is expensive.

Two passes end the game; the full board is revealed and Chinese area
scoring decides.

## Why it's interesting

- **Hidden opponent stones.** The server is the single source of truth
  and projects a per-player view that strips the opponent's stones
  before sending. The client physically can't see them.
- **Indistinguishable illegal responses.** The protocol has no `reason`
  field on illegal moves, enforced by structural tests. You get an
  `ILLEGAL` and a remaining-attempts count, nothing else — no way to
  deduce the opponent's position from probe reactions.
- **3-attempt auto-skip.** Every probe costs an attempt toward the turn.
  Three illegals in a row auto-pass the turn. Scanning the board one
  point at a time is a waste of turns.
- **20-second turn timer.** Stalling is auto-passed, so the pace stays
  playable.
- **Random matchmaking + private rooms.** The lobby works like online
  Go servers (OGS / KGS) — hub-and-spoke through a central matchmaker.
- **Chinese area scoring** (數子法) on the revealed final board.

## How it works

```
Browser / Desktop / Mobile / CLI
         │  JSON protocol (WebSocket)
         ▼
   Caddy (TLS)  →  uvicorn (FastAPI)  →  GameSession  →  core rules engine
                                             (per-player view projection happens here)
```

One server, many clients. The `core` rules engine is pure Python with
zero I/O. The `GameSession` owns the authoritative board and decides
what each client sees. All current clients — browser, desktop GUI, LAN
terminal, CLI hotseat — speak the same JSON protocol against the same
`GameSession`, so adding a new frontend (iOS app, Discord bot, anything
that can open a WebSocket) is zero server-side work.

## Roadmap

- [x] Core rules engine + tests
- [x] CLI hotseat
- [x] LAN TCP client / server
- [x] Browser UI (FastAPI + WebSocket, SVG board)
- [x] Desktop GUI (PySide6, packageable to `.exe`)
- [x] Matchmaker: random queue + private room codes
- [x] 20-second turn timer, 3-attempt auto-skip, back-to-lobby
- [x] Last-move marker, turn-change & countdown sound cues
- [x] Rematch with same opponent (colors swap automatically)
- [x] Move-number toggle (Show #) on web + desktop; SVG endgame snapshots in tests
- [x] Dead-stone marking phase: marker proposes, approver approves/rejects (pluggable resolver for future auto life/death detection)
- [x] Public deployment (AWS EC2 + Docker + Caddy + Let's Encrypt TLS)
- [ ] Online lobby — player list, direct challenges, ratings (OGS-style)
- [ ] Mobile client (iOS / Android)
- [ ] AI opponent — must respect the hidden-information handicap

---

Building locally, running tests, or deploying your own instance?
→ [**DEVELOPER.md**](DEVELOPER.md)

Full specification, architecture invariants, and design rationale:
[**CLAUDE.md**](CLAUDE.md)

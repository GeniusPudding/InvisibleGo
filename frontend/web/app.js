// Browser client for InvisibleGo.
//
// Three screens: lobby (choose matchmaking mode), waiting (connecting or
// holding a room code), game (board + sidebar). The WebSocket opens as
// soon as the player picks a lobby option; the first message they send is
// a lobby "join" command. Everything after the `welcome` message is the
// same per-move protocol as the LAN transport.

const BOARD_SIZE = 9;
const CELL = 60;
const OFFSET = 30;
const SVG_NS = "http://www.w3.org/2000/svg";
const COLS = "ABCDEFGHJ";

const EMPTY = 0, BLACK = 1, WHITE = 2;

let myColor = null;
let myTurn = false;
let ws = null;
let pendingPlay = null;
let myName = "";

// Screens
const lobbyScreen = document.getElementById("lobby");
const waitingScreen = document.getElementById("waiting");
const gameScreen = document.getElementById("game");

// Lobby controls
const nameInput = document.getElementById("name-input");
const randomBtn = document.getElementById("random-btn");
const createBtn = document.getElementById("create-btn");
const joinCodeInput = document.getElementById("join-code");
const joinBtn = document.getElementById("join-btn");
const lobbyMsg = document.getElementById("lobby-msg");

// Waiting screen
const waitingTitle = document.getElementById("waiting-title");
const waitingMsg = document.getElementById("waiting-msg");
const roomCodeDisplay = document.getElementById("room-code-display");
const roomCodeEl = document.getElementById("room-code");
const cancelBtn = document.getElementById("cancel-btn");

// Game screen
const statusEl = document.getElementById("status");
const colorLabel = document.getElementById("color-label");
const opponentLabel = document.getElementById("opponent-label");
const infoEl = document.getElementById("info");
const messageEl = document.getElementById("message");
const passBtn = document.getElementById("pass-btn");
const resignBtn = document.getElementById("resign-btn");

function show(screen) {
  lobbyScreen.classList.toggle("hidden", screen !== "lobby");
  waitingScreen.classList.toggle("hidden", screen !== "waiting");
  gameScreen.classList.toggle("hidden", screen !== "game");
}

function setMessage(text, kind) {
  messageEl.textContent = text || "";
  messageEl.className = kind || "";
}

function showLobbyError(text) {
  lobbyMsg.textContent = text || "";
}

// --- Board rendering (unchanged from before, but guarded by show("game")) ---

function svgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function intersectionXY(r, c) {
  return [OFFSET + c * CELL, OFFSET + r * CELL];
}

function initBoard() {
  const svg = document.getElementById("board");
  svg.innerHTML = "";
  for (let i = 0; i < BOARD_SIZE; i++) {
    const pos = OFFSET + i * CELL;
    svg.appendChild(svgEl("line", {
      x1: OFFSET, y1: pos,
      x2: OFFSET + (BOARD_SIZE - 1) * CELL, y2: pos,
      class: "line",
    }));
    svg.appendChild(svgEl("line", {
      x1: pos, y1: OFFSET,
      x2: pos, y2: OFFSET + (BOARD_SIZE - 1) * CELL,
      class: "line",
    }));
  }
  for (const [r, c] of [[2, 2], [2, 6], [4, 4], [6, 2], [6, 6]]) {
    const [x, y] = intersectionXY(r, c);
    svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 3, class: "star" }));
  }
  for (let c = 0; c < BOARD_SIZE; c++) {
    const [x] = intersectionXY(0, c);
    const t = svgEl("text", { x, y: OFFSET - 12, class: "coord" });
    t.textContent = COLS[c];
    svg.appendChild(t);
  }
  for (let r = 0; r < BOARD_SIZE; r++) {
    const [, y] = intersectionXY(r, 0);
    const t = svgEl("text", { x: OFFSET - 16, y: y + 4, class: "coord" });
    t.textContent = String(BOARD_SIZE - r);
    svg.appendChild(t);
  }
  svg.appendChild(svgEl("g", { id: "stones-layer" }));

  const hits = svgEl("g", { id: "hits-layer" });
  for (let r = 0; r < BOARD_SIZE; r++) {
    for (let c = 0; c < BOARD_SIZE; c++) {
      const [cx, cy] = intersectionXY(r, c);
      const hit = svgEl("circle", {
        cx, cy, r: CELL / 2 - 2, class: "hit",
      });
      hit.addEventListener("click", () => onIntersectionClick(r, c));
      hits.appendChild(hit);
    }
  }
  svg.appendChild(hits);
}

function setHitsLive(live) {
  const layer = document.getElementById("hits-layer");
  if (!layer) return;
  for (const hit of layer.children) {
    hit.classList.toggle("live", live);
  }
}

function renderStones(stones, revealAll) {
  const layer = document.getElementById("stones-layer");
  if (!layer) return;
  layer.innerHTML = "";
  for (let r = 0; r < BOARD_SIZE; r++) {
    for (let c = 0; c < BOARD_SIZE; c++) {
      const v = stones[r * BOARD_SIZE + c];
      if (v === EMPTY) continue;
      if (!revealAll && myColor !== null && v !== myColor) continue;
      const [cx, cy] = intersectionXY(r, c);
      layer.appendChild(svgEl("circle", {
        cx, cy, r: CELL / 2 - 5,
        class: "stone " + (v === BLACK ? "black" : "white"),
      }));
    }
  }
}

function placeStoneLocal(r, c, color) {
  const layer = document.getElementById("stones-layer");
  if (!layer) return;
  const [cx, cy] = intersectionXY(r, c);
  layer.appendChild(svgEl("circle", {
    cx, cy, r: CELL / 2 - 5,
    class: "stone " + (color === BLACK ? "black" : "white"),
  }));
}

function onIntersectionClick(r, c) {
  if (!myTurn || ws?.readyState !== WebSocket.OPEN) return;
  myTurn = false;
  pendingPlay = [r, c];
  setHitsLive(false);
  passBtn.disabled = true;
  resignBtn.disabled = true;
  ws.send(JSON.stringify({ type: "play", row: r, col: c }));
}

passBtn.addEventListener("click", () => {
  if (!myTurn || ws?.readyState !== WebSocket.OPEN) return;
  myTurn = false;
  setHitsLive(false);
  passBtn.disabled = true;
  resignBtn.disabled = true;
  ws.send(JSON.stringify({ type: "pass" }));
});

resignBtn.addEventListener("click", () => {
  if (!confirm("Resign the game?")) return;
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "resign" }));
  }
});

function setTurnControls(on) {
  myTurn = on;
  passBtn.disabled = !on;
  resignBtn.disabled = !on;
  setHitsLive(on);
  statusEl.textContent = on ? "Your turn." : "Waiting for opponent...";
}

// --- Lobby ---

function getName() {
  return (nameInput.value || "").trim().slice(0, 20) || "anon";
}

function openSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const s = new WebSocket(`${proto}//${location.host}/ws`);
  s.onmessage = (ev) => handleMessage(JSON.parse(ev.data));
  s.onclose = () => {
    if (gameScreen.classList.contains("hidden")) {
      // Still in lobby / waiting — tell the user
      showLobbyError("Connection closed.");
      show("lobby");
    } else {
      statusEl.textContent = "Disconnected.";
      setTurnControls(false);
    }
  };
  s.onerror = () => {
    showLobbyError("Connection error.");
  };
  return s;
}

randomBtn.addEventListener("click", () => {
  myName = getName();
  showLobbyError("");
  ws = openSocket();
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "join_random", name: myName }));
    waitingTitle.textContent = "Looking for a random opponent...";
    waitingMsg.textContent = "Matched as soon as another player joins.";
    roomCodeDisplay.classList.add("hidden");
    show("waiting");
  };
});

createBtn.addEventListener("click", () => {
  myName = getName();
  showLobbyError("");
  ws = openSocket();
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "create_room", name: myName }));
    waitingTitle.textContent = "Creating a private room...";
    waitingMsg.textContent = "";
    roomCodeDisplay.classList.add("hidden");
    show("waiting");
  };
});

joinBtn.addEventListener("click", () => {
  const code = (joinCodeInput.value || "").trim().toUpperCase();
  if (code.length < 4) {
    showLobbyError("Room code must be 4 characters.");
    return;
  }
  myName = getName();
  showLobbyError("");
  ws = openSocket();
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "join_room", name: myName, code }));
    waitingTitle.textContent = `Joining room ${code}...`;
    waitingMsg.textContent = "";
    roomCodeDisplay.classList.add("hidden");
    show("waiting");
  };
});

cancelBtn.addEventListener("click", () => {
  if (ws) ws.close();
  show("lobby");
});

// --- Message dispatch ---

function handleMessage(msg) {
  switch (msg.type) {
    case "room_created":
      waitingTitle.textContent = "Waiting for a friend to join...";
      waitingMsg.textContent = "";
      roomCodeEl.textContent = msg.code;
      roomCodeDisplay.classList.remove("hidden");
      break;

    case "room_error":
      showLobbyError(
        msg.reason === "not_found"
          ? "Room code not found."
          : `Room error: ${msg.reason}`
      );
      show("lobby");
      if (ws) ws.close();
      break;

    case "welcome":
      myColor = msg.color === "BLACK" ? BLACK : WHITE;
      colorLabel.textContent = `You are ${msg.color}`;
      colorLabel.style.background = msg.color === "BLACK" ? "#222" : "#fafafa";
      colorLabel.style.color = msg.color === "BLACK" ? "#eee" : "#222";
      colorLabel.style.border = "1px solid #999";
      opponentLabel.textContent = msg.opponent
        ? `vs. ${msg.opponent}`
        : "vs. opponent";
      setMessage("", null);
      show("game");
      initBoard();
      break;

    case "your_turn": {
      const v = msg.view;
      renderStones(v.your_stones, false);
      setTurnControls(true);
      infoEl.innerHTML = `
        Attempts this turn: <strong>${v.attempts_remaining}</strong><br>
        You have captured: <strong>${v.total_captured_by_me}</strong><br>
        Lost by you: <strong>${v.total_lost_by_me}</strong>
      `;
      if (msg.losses_since_last_turn > 0) {
        setMessage(
          `You lost ${msg.losses_since_last_turn} stone(s) since your last turn.`,
          "error"
        );
      } else {
        setMessage("Your turn. Click an intersection to play.", "ok");
      }
      break;
    }

    case "illegal":
      pendingPlay = null;
      if (msg.attempts_remaining > 0) {
        setMessage(
          `ILLEGAL move. ${msg.attempts_remaining} attempt(s) remaining.`,
          "error"
        );
        setTurnControls(true);
      } else {
        setMessage("Three illegal attempts. Turn auto-skipped.", "error");
        setTurnControls(false);
      }
      break;

    case "played":
      if (pendingPlay !== null) {
        placeStoneLocal(pendingPlay[0], pendingPlay[1], myColor);
        pendingPlay = null;
      }
      setMessage(
        msg.captured > 0
          ? `Move played. You captured ${msg.captured} stone(s).`
          : "Move played.",
        "ok"
      );
      setTurnControls(false);
      break;

    case "passed":
      setMessage("You passed.", "ok");
      setTurnControls(false);
      break;

    case "game_end": {
      renderStones(msg.full_board, true);
      setTurnControls(false);
      let result = msg.winner ? `${msg.winner} wins.` : "Draw.";
      if (msg.ended_by === "resign") result += ` (${msg.resigner} resigned.)`;
      if (msg.ended_by === "disconnect") result += ` (${msg.resigner} disconnected.)`;
      infoEl.innerHTML = `
        <strong>Game over.</strong><br>
        BLACK score: ${msg.black_score}<br>
        WHITE score: ${msg.white_score}<br>
        ${result}
      `;
      setMessage("Full board revealed.", "ok");
      statusEl.textContent = "Game over.";
      break;
    }

    case "error":
      setMessage(`Server error: ${msg.message}`, "error");
      break;
  }
}

show("lobby");

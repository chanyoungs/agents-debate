const topicEl = document.querySelector("#topic");
const statusLineEl = document.querySelector("#status-line");
const stateGridEl = document.querySelector("#state-grid");
const debatersEl = document.querySelector("#debaters");
const conclusionEl = document.querySelector("#conclusion");
const messagesEl = document.querySelector("#messages");
const emptyStateEl = document.querySelector("#empty-state");
const errorStateEl = document.querySelector("#error-state");
const pathForm = document.querySelector("#path-form");
const pathInput = document.querySelector("#path-input");
const togglePlaybackButton = document.querySelector("#toggle-playback-button");
const togglePlaybackIcon = document.querySelector("#toggle-playback-icon");
const noteForm = document.querySelector("#note-form");
const noteInput = document.querySelector("#note-input");
const pauseAfterNoteInput = document.querySelector("#pause-after-note");
const noteButton = document.querySelector("#note-button");
const pollingEl = document.querySelector("#polling");
const typingIndicatorEl = document.querySelector("#typing-indicator");
const runnerChipEl = document.querySelector("#runner-chip");

const params = new URLSearchParams(window.location.search);
let debatePath = params.get("path") || "";
let pollHandle = null;
let lastRenderedTurnId = 0;
const speakerPalette = [
  { bg: "#e0f2fe", fg: "#075985", ring: "rgba(14, 116, 144, 0.22)" },
  { bg: "#fef3c7", fg: "#92400e", ring: "rgba(180, 83, 9, 0.2)" },
  { bg: "#ede9fe", fg: "#6d28d9", ring: "rgba(109, 40, 217, 0.2)" },
  { bg: "#dcfce7", fg: "#166534", ring: "rgba(22, 101, 52, 0.2)" },
  { bg: "#ffe4e6", fg: "#be123c", ring: "rgba(190, 24, 93, 0.18)" },
  { bg: "#fce7f3", fg: "#9d174d", ring: "rgba(157, 23, 77, 0.18)" }
];

const debug = (...args) => {
  console.log("[agents-debate]", ...args);
};

if (debatePath) {
  pathInput.value = debatePath;
  debug("initial query path", debatePath);
}

function setError(message) {
  errorStateEl.textContent = message;
  errorStateEl.classList.remove("hidden");
}

function clearError() {
  errorStateEl.textContent = "";
  errorStateEl.classList.add("hidden");
}

function initialsFor(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function speakerMap(state) {
  const map = {
    Moderator: {
      cls: "speaker-moderator",
      avatar: "M",
      style: "--speaker-bg: #0f766e; --speaker-fg: #ffffff; --speaker-ring: rgba(15, 118, 110, 0.22);"
    },
    Operator: {
      cls: "speaker-operator",
      avatar: "O",
      style: "--speaker-bg: #111827; --speaker-fg: #ffffff; --speaker-ring: rgba(17, 24, 39, 0.22);"
    }
  };
  state.debaters.forEach((debater, index) => {
    const palette = speakerPalette[index % speakerPalette.length];
    map[debater.name] = {
      cls: `speaker-${index + 1}`,
      avatar: initialsFor(debater.name),
      style: `--speaker-bg: ${palette.bg}; --speaker-fg: ${palette.fg}; --speaker-ring: ${palette.ring};`
    };
  });
  return map;
}

function secondsSince(timestamp) {
  if (!timestamp) {
    return Number.POSITIVE_INFINITY;
  }
  const value = Date.parse(timestamp);
  if (Number.isNaN(value)) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.max(0, (Date.now() - value) / 1000);
}

function updateRunnerStatus(state) {
  const heartbeatAge = secondsSince(state.state.runner_heartbeat_at);
  const phase = (state.state.runner_phase || "idle").trim();
  const live = heartbeatAge <= 4;
  const stale = heartbeatAge > 8;

  runnerChipEl.classList.remove("runner-chip--live", "runner-chip--paused", "runner-chip--stale");
  if (stale) {
    runnerChipEl.textContent = "Runner: offline";
    runnerChipEl.classList.add("runner-chip--stale");
    return;
  }
  if (phase === "paused") {
    runnerChipEl.textContent = "Runner: paused";
    runnerChipEl.classList.add("runner-chip--paused");
    return;
  }
  if (live) {
    runnerChipEl.textContent = phase === "thinking" ? "Runner: active" : "Runner: live";
    runnerChipEl.classList.add("runner-chip--live");
    return;
  }
  runnerChipEl.textContent = "Runner: idle";
}

function scrollMessagesToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderState(state) {
  topicEl.textContent = state.topic || "Untitled debate";
  statusLineEl.textContent = `${state.state.status} • round ${state.state.round} • next: ${state.state.next_speaker}`;
  pollingEl.textContent = state.state.paused ? "Paused" : "Polling every 2s";
  pollingEl.classList.toggle("polling-chip--paused", Boolean(state.state.paused));
  const speakers = speakerMap(state);
  const typingSpeaker = (state.state.typing_speaker || "").trim();
  const pendingNote = (state.state.pending_note || "").trim();
  updateRunnerStatus(state);

  const items = [
    ["Status", state.state.status],
    ["Round", String(state.state.round)],
    ["Next", state.state.next_speaker],
    ["Turns", String(state.state.turn_count)],
    ["Updated", state.state.updated_at || "Unknown"],
    ["Paused", state.state.paused ? "Yes" : "No"],
    ["Pending Note", pendingNote || "None"],
    ["Runner Phase", state.state.runner_phase || "Unknown"],
    ["Runner Heartbeat", state.state.runner_heartbeat_at || "Unknown"]
  ];
  stateGridEl.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="state-item">
          <dt>${label}</dt>
          <dd>${value}</dd>
        </div>
      `
    )
    .join("");

  debatersEl.innerHTML = state.debaters
    .map((debater) => {
      const active = debater.name === state.state.next_speaker ? " debater-card--active" : "";
      const isTyping = debater.name === typingSpeaker;
      const pill = isTyping
        ? '<span class="active-pill active-pill--typing">Writing</span>'
        : debater.name === state.state.next_speaker
          ? '<span class="active-pill">On deck</span>'
          : "";
      const identity = speakers[debater.name];
      return `
        <article class="debater-card${active}" style="${identity.style}">
          <div class="debater-head">
            <div class="debater-ident">
              <span class="debater-avatar">${identity.avatar}</span>
              <h3>${debater.name}</h3>
            </div>
            ${pill}
          </div>
          <p class="stance">${debater.stance}</p>
          <p class="role">${debater.role}</p>
          <p class="context">${debater.context}</p>
        </article>
      `;
    })
    .join("");

  const conclusion = state.conclusion?.text?.trim();
  conclusionEl.textContent = conclusion || "No conclusion yet.";
  conclusionEl.classList.toggle("empty", !conclusion);
  togglePlaybackButton.disabled = state.state.status === "complete";
  togglePlaybackButton.setAttribute("aria-label", state.state.paused ? "Resume debate" : "Pause debate");
  togglePlaybackButton.setAttribute("title", state.state.paused ? "Resume debate" : "Pause debate");
  togglePlaybackIcon.textContent = state.state.paused ? ">" : "||";

  if (typingSpeaker) {
    typingIndicatorEl.textContent = `${typingSpeaker} is writing`;
    typingIndicatorEl.classList.remove("hidden");
  } else {
    typingIndicatorEl.textContent = "";
    typingIndicatorEl.classList.add("hidden");
  }

  messagesEl.innerHTML = state.turns
    .map((turn) => {
      const speakerClass =
        turn.speaker === "Moderator"
          ? "message--moderator"
          : turn.speaker === "Operator"
            ? "message--operator"
            : "message--debater";
      const identity = speakers[turn.speaker] || speakers.Moderator;
      const safeText = escapeHtml(turn.text).replace(/\n/g, "<br />");
      return `
        <article class="message ${speakerClass}" style="${identity.style}">
          <div class="message-meta">
            <span class="message-avatar">${identity.avatar}</span>
            <span class="turn-id">Turn ${turn.id}</span>
            <span class="speaker">${turn.speaker}</span>
            <span class="timestamp">${turn.timestamp || ""}</span>
          </div>
          <p class="message-body">${safeText}</p>
        </article>
      `;
    })
    .join("");

  const currentTurnId = state.turns.length > 0 ? state.turns[state.turns.length - 1].id : 0;
  if (currentTurnId !== lastRenderedTurnId) {
    scrollMessagesToBottom();
    lastRenderedTurnId = currentTurnId;
  }

  const hasTurns = state.turns && state.turns.length > 0;
  emptyStateEl.classList.toggle("hidden", hasTurns);
}

async function sendControl(action, extra = {}) {
  if (!debatePath) {
    setError("Load a debate file before sending controls.");
    return;
  }
  clearError();
  try {
    const response = await fetch(`/api/control?path=${encodeURIComponent(debatePath)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error((payload.errors || ["Control request failed"]).join("\n"));
    }
    renderState(payload);
  } catch (error) {
    console.error("[agents-debate] sendControl failed", error);
    setError(error.message);
  }
}

async function loadDebate() {
  if (!debatePath) {
    debug("loadDebate skipped: no debatePath");
    return;
  }
  clearError();
  try {
    debug("loading debate", debatePath);
    const response = await fetch(`/api/debate?path=${encodeURIComponent(debatePath)}`, { cache: "no-store" });
    const rawText = await response.text();
    debug("api status", response.status);
    debug("api raw payload", rawText.slice(0, 1200));
    let payload;
    try {
      payload = JSON.parse(rawText);
    } catch (parseError) {
      throw new Error(`API returned non-JSON payload: ${rawText.slice(0, 240)}`);
    }
    if (!response.ok) {
      throw new Error((payload.errors || ["Failed to load debate"]).join("\n"));
    }
    const state = payload && payload.topic ? payload : payload.state;
    if (!state || !state.topic || !state.state) {
      debug("invalid parsed payload", payload);
      throw new Error("API returned an invalid debate payload");
    }
    debug("rendering state", {
      topic: state.topic,
      status: state.state.status,
      next: state.state.next_speaker,
      turns: state.turns?.length
    });
    try {
      renderState(state);
    } catch (renderError) {
      debug("renderState failed", {
        message: renderError.message,
        stack: renderError.stack
      });
      throw renderError;
    }
  } catch (error) {
    console.error("[agents-debate] loadDebate failed", error);
    setError(error.message);
  }
}

async function bootstrapDefaultPath() {
  if (debatePath) {
    return;
  }
  try {
    debug("bootstrapping default path");
    const response = await fetch("/api/config", { cache: "no-store" });
    const rawText = await response.text();
    debug("config status", response.status);
    debug("config raw payload", rawText);
    const payload = JSON.parse(rawText);
    if (!response.ok) {
      return;
    }
    if (payload.default_path) {
      debatePath = payload.default_path;
      pathInput.value = debatePath;
      debug("using default path", debatePath);
      const next = new URL(window.location.href);
      next.searchParams.set("path", debatePath);
      window.history.replaceState({}, "", next);
    }
  } catch (_error) {
    console.error("[agents-debate] bootstrapDefaultPath failed", _error);
    return;
  }
}

function startPolling() {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
  if (!debatePath) {
    return;
  }
  loadDebate();
  pollHandle = setInterval(loadDebate, 2000);
}

pathForm.addEventListener("submit", (event) => {
  event.preventDefault();
  debatePath = pathInput.value.trim();
  debug("path form submit", debatePath);
  const next = new URL(window.location.href);
  if (debatePath) {
    next.searchParams.set("path", debatePath);
  } else {
    next.searchParams.delete("path");
  }
  window.history.replaceState({}, "", next);
  startPolling();
});

togglePlaybackButton.addEventListener("click", () => {
  const action = togglePlaybackIcon.textContent === ">" ? "resume" : "pause";
  sendControl(action);
});

noteForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const note = noteInput.value.trim();
  if (!note) {
    setError("Moderator note must not be empty.");
    return;
  }
  sendControl("note", {
    note,
    pause_after_note: pauseAfterNoteInput.checked
  }).then(() => {
    noteInput.value = "";
    pauseAfterNoteInput.checked = false;
  });
});

async function init() {
  await bootstrapDefaultPath();
  startPolling();
}

init();

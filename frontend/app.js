const state = {
  queue: [],
  filterLevel: "all",
  search: "",
  selectedId: null,
};

const $ = (sel) => document.querySelector(sel);
const queueListEl = $("#queueList");
const detailPane = $("#detailPane");
const briefEl = $("#brief");

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmtMoney(n) {
  return "$" + Number(n).toLocaleString();
}

function badge(level) {
  return `<span class="badge ${level}">${level}</span>`;
}

async function loadQueue() {
  const data = await api("/api/queue");
  state.queue = data.cases;
  briefEl.innerHTML =
    `<span><b>${data.total}</b> cases in queue</span>` +
    `<span class="b-high">${data.counts.high} high</span>` +
    `<span class="b-medium">${data.counts.medium} medium</span>` +
    `<span class="b-low">${data.counts.low} low</span>` +
    `<span class="engine-tag">reasoning: ${data.engine}</span>`;
  renderQueueList();
}

function renderQueueList() {
  const term = state.search.trim().toLowerCase();
  const rows = state.queue.filter((c) => {
    if (state.filterLevel !== "all" && c.risk_level !== state.filterLevel) return false;
    if (!term) return true;
    return (
      c.case_id.toLowerCase().includes(term) ||
      c.claim_number.toLowerCase().includes(term) ||
      c.state.toLowerCase().includes(term) ||
      c.care_type.toLowerCase().includes(term)
    );
  });

  if (rows.length === 0) {
    queueListEl.innerHTML = `<div class="empty-state">No cases match this filter.</div>`;
    return;
  }

  queueListEl.innerHTML = rows
    .map(
      (c) => `
    <button class="queue-item ${c.case_id === state.selectedId ? "selected" : ""}" data-id="${c.case_id}">
      <div class="qi-top">
        <span class="qi-id">${c.case_id}</span>
        ${badge(c.risk_level)}
      </div>
      <div class="qi-meta">${c.care_type} · ${fmtMoney(c.claim_amount_usd)} · ${c.state} · ${c.claim_date}</div>
      <div class="qi-summary">${c.summary}</div>
      ${c.decision !== "pending" ? `<div class="qi-decision">Marked: ${c.decision}</div>` : ""}
    </button>`
    )
    .join("");

  queueListEl.querySelectorAll(".queue-item").forEach((btn) => {
    btn.addEventListener("click", () => selectCase(btn.dataset.id));
  });
}

async function selectCase(caseId) {
  state.selectedId = caseId;
  renderQueueList();
  detailPane.innerHTML = `<div class="empty-state">Loading case ${caseId}…</div>`;
  const data = await api(`/api/cases/${caseId}`);
  renderDetail(data);
}

function renderDetail(data) {
  const { case: c, assessment: a, investigator_state: inv } = data;

  const indicatorsHtml = a.indicators.length
    ? a.indicators
        .map(
          (i) => `
      <div class="indicator">
        <div class="indicator-weight">+${i.weight}</div>
        <div class="indicator-body">
          <div>${i.explanation}</div>
          <div class="indicator-signal">${i.signal} = ${i.value}</div>
        </div>
      </div>`
        )
        .join("")
    : `<div class="no-indicators">No fraud signals triggered on this case.</div>`;

  const notesHtml = inv.notes.length
    ? inv.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")
    : `<li class="chat-empty" style="list-style:none;">No notes yet.</li>`;

  const chatHtml = inv.chat_history.length
    ? inv.chat_history
        .map((m) => `<div class="chat-msg ${m.role}">${escapeHtml(m.content)}</div>`)
        .join("")
    : `<div class="chat-empty">Ask the AI a follow-up question about this case — e.g. "why is distance flagged?"</div>`;

  detailPane.innerHTML = `
    <div class="case-header">
      <div>
        <h2>${c.case_id} <span style="font-size:16px;color:var(--muted);font-family:var(--sans);">— ${c.claim_number}</span></h2>
        <div class="sub">${c.care_type} · ${c.state} · filed ${c.claim_date}</div>
      </div>
      <div class="risk-score-block">
        ${badge(a.risk_level)}
        <div class="score">${a.risk_score}</div>
        <div class="conf">confidence: ${a.confidence}</div>
      </div>
    </div>

    <div class="attrs-grid">
      <div><div class="attr-label">Claim amount</div><div class="attr-value">${fmtMoney(c.claim_amount_usd)}</div></div>
      <div><div class="attr-label">Distance (mi)</div><div class="attr-value">${c.member_provider_distance_miles}</div></div>
      <div><div class="attr-label">Visits / week</div><div class="attr-value">${c.weekly_visit_frequency}</div></div>
      <div><div class="attr-label">Prior claims (12mo)</div><div class="attr-value">${c.prior_claims_last_12mo}</div></div>
      <div><div class="attr-label">vs. peer avg</div><div class="attr-value">${c.amount_vs_peer_avg_pct}%</div></div>
      <div><div class="attr-label">Weekend billing</div><div class="attr-value">${Math.round(c.weekend_billing_ratio * 100)}%</div></div>
    </div>

    <div class="panel">
      <h3>AI assessment</h3>
      <p class="summary-text">${a.summary}</p>
    </div>

    <div class="panel">
      <h3>Key indicators</h3>
      ${indicatorsHtml}
    </div>

    <div class="panel action-callout">
      <div>
        <h3 style="margin-bottom:4px;">Recommended next step</h3>
        <div class="action-text">${a.recommended_action}</div>
      </div>
      <div class="decision-buttons">
        <button class="btn accept ${inv.decision === "accepted" ? "active" : ""}" id="acceptBtn">Accept finding</button>
        <button class="btn reject ${inv.decision === "rejected" ? "active" : ""}" id="rejectBtn">Override / reject</button>
      </div>
    </div>

    <div class="panel">
      <h3>Investigator notes</h3>
      <ul class="notes-list">${notesHtml}</ul>
      <form class="note-form" id="noteForm">
        <textarea id="noteInput" placeholder="Add a note for the case file…"></textarea>
        <button class="btn primary" type="submit">Save</button>
      </form>
    </div>

    <div class="panel">
      <h3>Ask a follow-up question</h3>
      <div class="chat-log" id="chatLog">${chatHtml}</div>
      <form class="chat-form" id="chatForm">
        <input id="chatInput" type="text" placeholder="e.g. why is this flagged high risk?" />
        <button class="btn primary" type="submit">Ask</button>
      </form>
    </div>
  `;

  $("#acceptBtn").addEventListener("click", () => setDecision(c.case_id, "accepted"));
  $("#rejectBtn").addEventListener("click", () => setDecision(c.case_id, "rejected"));

  $("#noteForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#noteInput");
    if (!input.value.trim()) return;
    await api(`/api/cases/${c.case_id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: input.value.trim() }),
    });
    const fresh = await api(`/api/cases/${c.case_id}`);
    renderDetail(fresh);
  });

  $("#chatForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#chatInput");
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    const chatLog = $("#chatLog");
    chatLog.innerHTML += `<div class="chat-msg investigator">${escapeHtml(q)}</div>`;
    chatLog.scrollTop = chatLog.scrollHeight;
    const res = await api(`/api/cases/${c.case_id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    chatLog.innerHTML += `<div class="chat-msg assistant">${escapeHtml(res.answer)}</div>`;
    chatLog.scrollTop = chatLog.scrollHeight;
  });
}

async function setDecision(caseId, decision) {
  // toggle back to pending if clicking the already-active choice
  const current = state.queue.find((c) => c.case_id === caseId);
  const inv = await api(`/api/cases/${caseId}`);
  const next = inv.investigator_state.decision === decision ? "pending" : decision;
  await api(`/api/cases/${caseId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: next }),
  });
  await loadQueue();
  const fresh = await api(`/api/cases/${caseId}`);
  renderDetail(fresh);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

$("#search").addEventListener("input", (e) => {
  state.search = e.target.value;
  renderQueueList();
});

$("#filterChips").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.filterLevel = btn.dataset.level;
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  btn.classList.add("active");
  renderQueueList();
});

loadQueue();

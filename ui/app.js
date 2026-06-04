// Multi-Agent Orchestration UI — vanilla JS only.

const els = {
  sampleList: document.getElementById("sampleList"),
  requestInput: document.getElementById("requestInput"),
  runBtn: document.getElementById("runBtn"),
  llmBadge: document.getElementById("llmBadge"),
  runIdBadge: document.getElementById("runIdBadge"),
  viewLogBtn: document.getElementById("viewLogBtn"),
  planSub: document.getElementById("planSub"),
  dag: document.getElementById("dag"),
  trace: document.getElementById("trace"),
  bCost: document.getElementById("bCost"),
  bTokens: document.getElementById("bTokens"),
  bLatency: document.getElementById("bLatency"),
  bCalls: document.getElementById("bCalls"),
  result: document.getElementById("result"),
  drawer: document.getElementById("drawer"),
  drawerOverlay: document.getElementById("drawerOverlay"),
  drawerTitle: document.getElementById("drawerTitle"),
  drawerRef: document.getElementById("drawerRef"),
  drawerBody: document.getElementById("drawerBody"),
  drawerClose: document.getElementById("drawerClose"),
};

// Holds the artifacts written during the current run so the drawer can show them.
const artifacts = {};         // ref -> data
const nodesByName = {};       // logical node name -> { el, ref }
let activeSampleName = null;
let currentRunId = null;

// ---------- Init ----------
window.addEventListener("DOMContentLoaded", async () => {
  await loadSamples();
  setupDrawer();
  els.runBtn.addEventListener("click", runPipeline);
  els.viewLogBtn.addEventListener("click", viewCurrentRunLog);
  // Quick LLM hint — the server uses real API only if ANTHROPIC_API_KEY is set on its end.
  els.llmBadge.textContent = "LLM: mock (offline-safe)";
  els.llmBadge.className = "badge badge-info";
});

async function viewCurrentRunLog() {
  if (!currentRunId) return;
  try {
    const resp = await fetch(`/api/logs/${currentRunId}`);
    if (!resp.ok) {
      openDrawer("log (not found)", currentRunId, await resp.text());
      return;
    }
    const data = await resp.json();
    openDrawer(`run.log`, `runs/${data.run_id}/run.log`, data.log);
  } catch (e) {
    openDrawer("log (error)", currentRunId, String(e));
  }
}

// ---------- Samples ----------
async function loadSamples() {
  try {
    const resp = await fetch("/api/samples");
    const samples = await resp.json();
    els.sampleList.innerHTML = "";
    samples.forEach((s, idx) => {
      const card = document.createElement("div");
      card.className = "sample";
      card.dataset.name = s.name;
      card.innerHTML = `
        <div class="sample-head">
          <div class="sample-title">${escapeHtml(s.title)}</div>
          <span class="sample-tag sample-tag-${s.tag}">${escapeHtml(s.tag)}</span>
        </div>
        <div class="sample-desc">${escapeHtml(s.description)}</div>
      `;
      card.addEventListener("click", () => selectSample(s.name, card));
      els.sampleList.appendChild(card);
      if (idx === 0) selectSample(s.name, card);
    });
  } catch (e) {
    els.sampleList.innerHTML = `<div class="muted">Could not load samples (${escapeHtml(String(e))}).</div>`;
  }
}

async function selectSample(name, cardEl) {
  document.querySelectorAll(".sample").forEach(el => el.classList.remove("active"));
  cardEl.classList.add("active");
  activeSampleName = name;
  try {
    const resp = await fetch(`/api/samples/${name}`);
    const data = await resp.json();
    els.requestInput.value = JSON.stringify(
      { request: data.request, sources: data.sources },
      null,
      2,
    );
  } catch (e) {
    els.requestInput.value = "";
  }
}

// ---------- Run pipeline ----------
async function runPipeline() {
  let body;
  try {
    body = JSON.parse(els.requestInput.value);
  } catch (e) {
    flashError("The request must be valid JSON: " + e.message);
    return;
  }

  // Reset UI state.
  els.runBtn.disabled = true;
  els.runBtn.textContent = "Running…";
  els.trace.innerHTML = "";
  els.dag.innerHTML = "";
  els.result.innerHTML = `<div class="muted">Running pipeline…</div>`;
  Object.keys(artifacts).forEach(k => delete artifacts[k]);
  Object.keys(nodesByName).forEach(k => delete nodesByName[k]);
  setBudget({ cost_usd: 0, tokens_in: 0, tokens_out: 0, cumulative_latency_ms: 0, calls: 0 });

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok || !resp.body) {
      const text = await resp.text();
      flashError("Run failed: " + text);
    } else {
      await consumeSSE(resp.body);
    }
  } catch (e) {
    flashError("Run failed: " + e.message);
  } finally {
    els.runBtn.disabled = false;
    els.runBtn.textContent = "Run pipeline →";
  }
}

async function consumeSSE(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;
  try {
    while (!done) {
      const { value, done: streamDone } = await reader.read();
      done = streamDone;
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop();
        for (const chunk of chunks) {
          const line = chunk.split("\n").find(l => l.startsWith("data: "));
          if (!line) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            handleEvent(evt);
            if (evt.kind === "done" || evt.kind === "error") done = true;
          } catch (e) {
            // ignore malformed line
          }
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

// ---------- Event handlers ----------
function handleEvent(evt) {
  switch (evt.kind) {
    case "plan":       return onPlan(evt.payload);
    case "node_start": return onNodeStart(evt.node, evt.payload);
    case "gate":       return onGate(evt.node, evt.payload);
    case "node_done":  return onNodeDone(evt.node, evt.payload);
    case "artifact":   return onArtifact(evt.node, evt.payload);
    case "budget":     return setBudget(evt.payload);
    case "done":       return onDone(evt.payload);
    case "error":      return onError(evt.payload);
  }
}

function onPlan(payload) {
  currentRunId = payload.run_id;
  els.runIdBadge.textContent = `run: ${payload.run_id}`;
  els.runIdBadge.className = "badge badge-info";
  els.viewLogBtn.disabled = false;
  els.planSub.textContent = payload.request || "(no request text)";
  renderDag(payload.plan);
  pushTrace("plan", null, `shape=<b>${escapeHtml(payload.plan.shape)}</b>`);
}

function renderDag(plan) {
  els.dag.innerHTML = "";
  if (plan.shape === "clarification") {
    const col = document.createElement("div");
    col.className = "dag-col";
    col.appendChild(makeNodeEl("planner", "planner", "needs clarification", "fail"));
    els.dag.appendChild(col);
    return;
  }
  const cols = [];

  // Retrievers (parallel)
  const retCol = document.createElement("div");
  retCol.className = "dag-col";
  for (const id of plan.retrievers) {
    const name = `retriever:${id}`;
    const el = makeNodeEl(name, "retriever", id, "pending");
    retCol.appendChild(el);
    nodesByName[name] = { el, ref: null };
  }
  cols.push(retCol);

  // Cleaner
  const cleanCol = document.createElement("div");
  cleanCol.className = "dag-col";
  const cleanEl = makeNodeEl("cleaner", "cleaner", "normalize · dedupe", "pending");
  cleanCol.appendChild(cleanEl);
  nodesByName["cleaner"] = { el: cleanEl, ref: null };
  cols.push(cleanCol);

  // Analysts (parallel)
  const anaCol = document.createElement("div");
  anaCol.className = "dag-col";
  for (const a of plan.analysts) {
    const name = `analyst:${a}`;
    const el = makeNodeEl(name, "analyst", a, "pending");
    anaCol.appendChild(el);
    nodesByName[name] = { el, ref: null };
  }
  cols.push(anaCol);

  // Writer
  const wrCol = document.createElement("div");
  wrCol.className = "dag-col";
  const wrEl = makeNodeEl("writer", "writer", "uses LLM", "pending");
  wrCol.appendChild(wrEl);
  nodesByName["writer"] = { el: wrEl, ref: null };
  cols.push(wrCol);

  // Verifier
  const vCol = document.createElement("div");
  vCol.className = "dag-col";
  const vEl = makeNodeEl("verifier", "verifier", "claim ⊆ findings", "pending");
  vCol.appendChild(vEl);
  nodesByName["verifier"] = { el: vEl, ref: null };
  cols.push(vCol);

  for (let i = 0; i < cols.length; i++) {
    els.dag.appendChild(cols[i]);
    if (i < cols.length - 1) els.dag.appendChild(makeArrow());
  }
}

function makeNodeEl(name, kind, sub, state) {
  const div = document.createElement("div");
  div.className = `node state-${state}`;
  div.dataset.name = name;
  div.innerHTML = `
    <div class="node-head">
      <div>
        <div class="node-kind">${escapeHtml(kind)}</div>
        <div class="node-name">${escapeHtml(name)}</div>
      </div>
      <div class="node-status"></div>
    </div>
    <div class="node-meta">${escapeHtml(sub)}</div>
  `;
  div.addEventListener("click", () => {
    const entry = nodesByName[name];
    if (entry && entry.ref && artifacts[entry.ref]) {
      openDrawer(name, entry.ref, artifacts[entry.ref]);
    } else {
      openDrawer(name, "(no artifact yet)", { state: "pending" });
    }
  });
  return div;
}

function makeArrow() {
  const div = document.createElement("div");
  div.className = "dag-arrow";
  div.innerHTML = `<svg width="40" height="20" viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <line x1="0" y1="10" x2="28" y2="10" stroke="currentColor" stroke-width="1.5"/>
    <polygon points="26,5 37,10 26,15" fill="currentColor"/>
  </svg>`;
  return div;
}

function setNodeState(name, state) {
  const entry = nodesByName[name];
  if (!entry) return;
  entry.el.classList.remove("state-pending", "state-running", "state-ok", "state-fail", "state-warn");
  entry.el.classList.add(`state-${state}`);
}

function onNodeStart(name, payload) {
  setNodeState(name, "running");
  pushTrace("node_start", name, `attempt ${payload.attempt}`);
}

function onGate(name, payload) {
  if (payload.retrying) {
    pushTrace("gate", name, `retry scheduled (attempt ${payload.attempt})`);
    return;
  }
  if (payload.ok) {
    pushTrace("gate", name, `<span class="gate-pass">passed</span>`, payload.warnings);
  } else {
    setNodeState(name, "fail");
    pushTrace(
      "gate",
      name,
      `<span class="gate-fail">rejected</span>`,
      payload.violations,
      "fail",
    );
  }
}

function onNodeDone(name, payload) {
  if (payload.terminal) {
    setNodeState(name, "fail");
    pushTrace("node_done", name, `terminal failure after retries`, payload.violations, "fail");
    return;
  }
  setNodeState(name, "ok");
  const env = payload.envelope || {};
  const prov = env.provenance || {};
  const tokens = prov.tokens || {};
  const tIn = tokens.in ?? tokens.in_ ?? 0;
  const tOut = tokens.out ?? 0;
  const meta = `model=${escapeHtml(prov.model || "?")} · tok ${tIn}/${tOut} · ${prov.latency_ms ?? 0}ms · conf ${env.confidence ?? "?"}`;
  pushTrace("node_done", name, meta);
}

function onArtifact(name, payload) {
  artifacts[payload.ref] = payload.data;
  const entry = nodesByName[name];
  if (entry) entry.ref = payload.ref;
  pushTrace("artifact", name, `<span class="mono">${escapeHtml(payload.ref)}</span> written`);
}

function setBudget(b) {
  els.bCost.textContent = `$${(b.cost_usd ?? 0).toFixed(4)}`;
  els.bTokens.textContent = `${b.tokens_in ?? 0} / ${b.tokens_out ?? 0}`;
  els.bLatency.textContent = `${b.cumulative_latency_ms ?? 0}`;
  els.bCalls.textContent = `${b.calls ?? 0}`;
}

function onDone(payload) {
  if (payload.verdict === "pass") renderResultPass(payload);
  else if (payload.verdict === "degraded") renderResultDegraded(payload);
  else if (payload.verdict === "clarification_needed") renderClarification(payload);
  else if (payload.verdict === "fail") renderResultFail(payload);
  else renderResultUnknown(payload);
  pushTrace("done", null, `verdict=<b>${escapeHtml(payload.verdict)}</b>`);
}

function renderResultPass(p) {
  const provHtml = (p.provenance_chain || [])
    .map((r, i, arr) => {
      const arrow = i < arr.length - 1 ? '<span class="provenance-arrow">↑</span>' : "";
      return `<div class="provenance-row" data-ref="${escapeHtml(r)}">
        <span>${escapeHtml(r)}</span>${arrow}<span class="provenance-open"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></span>
      </div>`;
    })
    .join("");

  els.result.innerHTML = `
    <div><span class="result-verdict verdict-pass">✓ verifier: pass</span></div>
    <div class="result-summary">${escapeHtml(p.summary)}</div>
    <div class="result-meta">
      ${(p.claims_used || []).map(c => `<span class="chip chip-strong">${escapeHtml(c)}</span>`).join("")}
      ${(p.sections || []).map(s => `<span class="chip">${escapeHtml(s)}</span>`).join("")}
    </div>
    <div>
      <div class="section-title" style="margin-bottom:6px">Provenance chain</div>
      <div class="provenance">${provHtml}</div>
    </div>
  `;
  // Hook up provenance click → drawer
  els.result.querySelectorAll(".provenance-row").forEach(row => {
    row.addEventListener("click", () => {
      const ref = row.dataset.ref;
      if (artifacts[ref]) openDrawer(ref.split("/")[1] || ref, ref, artifacts[ref]);
    });
  });
}

function renderResultDegraded(p) {
  els.result.innerHTML = `
    <div><span class="result-verdict verdict-degraded">⚠ degraded — ${escapeHtml(p.code || "")}</span></div>
    <div class="result-summary">${escapeHtml(p.message)}</div>
    <div class="muted" style="font-size:12px">No customer-facing summary was produced — the system refused to fabricate one. This is the §9.1 contract: a failed dependency is a first-class decision, never a silent skip.</div>
  `;
}

function renderClarification(p) {
  els.result.innerHTML = `
    <div><span class="result-verdict verdict-clarification">? clarification needed</span></div>
    <div class="result-summary">${escapeHtml(p.message)}</div>
  `;
}

function renderResultFail(p) {
  els.result.innerHTML = `
    <div><span class="result-verdict verdict-fail">✗ verifier: fail</span></div>
    <div class="result-summary">${escapeHtml(p.summary || "")}</div>
    <div class="muted">Violations:</div>
    <pre class="mono">${escapeHtml(JSON.stringify(p.violations || [], null, 2))}</pre>
  `;
}

function renderResultUnknown(p) {
  els.result.innerHTML = `<pre class="mono">${escapeHtml(JSON.stringify(p, null, 2))}</pre>`;
}

function onError(payload) {
  flashError(payload.message || "unknown error");
}

// ---------- Trace ----------
function pushTrace(kind, node, html, list, mark) {
  const row = document.createElement("div");
  row.className = "trace-row";
  row.innerHTML = `
    <div class="trace-kind trace-kind-${kind}">${escapeHtml(kind.replace("_", " "))}</div>
    <div class="trace-node">${escapeHtml(node || "")}</div>
    <div class="trace-detail">${html}${list && list.length ? listHtml(list, mark) : ""}</div>
  `;
  els.trace.appendChild(row);
  els.trace.scrollTop = els.trace.scrollHeight;
}

function listHtml(items, mark) {
  if (!items || !items.length) return "";
  const cls = mark === "fail" ? "violations" : "muted";
  return `<div class="${cls}">${items.map(escapeHtml).join("<br>")}</div>`;
}

// ---------- Drawer ----------
function setupDrawer() {
  const close = () => {
    els.drawer.classList.remove("open");
    els.drawerOverlay.classList.remove("open");
  };
  els.drawerClose.addEventListener("click", close);
  els.drawerOverlay.addEventListener("click", close);
  document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
}

function openDrawer(title, ref, data) {
  els.drawerTitle.textContent = title;
  els.drawerRef.textContent = ref;
  els.drawerBody.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  els.drawer.classList.add("open");
  els.drawerOverlay.classList.add("open");
}

// ---------- Util ----------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function flashError(msg) {
  pushTrace("error", null, escapeHtml(msg), null, "fail");
}

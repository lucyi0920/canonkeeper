const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const assetUrl = (ref) => (ref ? `/api/assets/${encodeURIComponent(ref)}` : "");

const state = { session: null, canon: null, selected: null, busy: false, edit: null };

async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}

function toast(msg, ok = false) {
  const el = document.createElement("div");
  el.className = "toast" + (ok ? " ok" : "");
  el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

/* ---------- trace ---------- */
let polling = null;
function startTrace(runId, label) {
  $("trace").innerHTML = "";
  $("runstate").textContent = label + " · running";
  let stop = false;
  const tick = async () => {
    if (stop) return;
    try {
      const run = await api("GET", `/api/runs/${runId}`);
      renderTrace(run.steps || []);
    } catch { /* keep polling */ }
    if (!stop) polling = setTimeout(tick, 800);
  };
  tick();
  return async () => {
    stop = true;
    clearTimeout(polling);
    try { const run = await api("GET", `/api/runs/${runId}`); renderTrace(run.steps || []); } catch { /* ignore */ }
    $("runstate").textContent = label + " · done";
  };
}

function renderTrace(steps) {
  const byId = new Map();
  for (const s of steps) byId.set(s.id, s);
  const rows = [...byId.values()].sort((a, b) => a.t_ms - b.t_ms);
  if (!rows.length) { $("trace").innerHTML = `<div class="empty">Starting…</div>`; return; }
  $("trace").innerHTML = rows.map((s) => {
    const dur = s.status === "running" ? "…" : s.duration_ms ? (s.duration_ms / 1000).toFixed(1) + "s" : (s.t_ms / 1000).toFixed(1) + "s";
    return `<div class="st ${esc(s.status)}"><span class="d"></span>
      <span class="who">${esc(s.actor)}${s.model ? `<small>${esc(s.model)}</small>` : ""}</span>
      <span class="act">${esc(s.action)}${s.detail ? `<span class="det">${esc(s.detail)}</span>` : ""}</span>
      <span class="t">${dur}</span></div>`;
  }).join("");
  $("trace").scrollTop = $("trace").scrollHeight;
}

/* ---------- header / canon ---------- */
function renderCanon() {
  const c = state.canon;
  const title = c.series_title || c.bible.series_title;
  const m = title.match(/^(.*?)\s*\((.*)\)\s*$/);
  $("series").innerHTML = m ? `${esc(m[1])} <span class="kr">${esc(m[2])}</span>` : esc(title);
  const tok = c.context?.input_tokens || 0;
  $("tok").textContent = tok.toLocaleString();
  $("tokbar").style.width = Math.max(1, Math.min(100, tok / 10000)) + "%";
  $("tokpct").textContent = `${c.episodes.length} episodes`;
  const v = c.verification || {};
  $("facts").textContent = `facts verified ${v.verified ?? "—"}/${v.total ?? "—"}`;
  $("chars").innerHTML = c.bible.characters.map((ch) => {
    const t = ch.traits.find((x) => x.side && x.side !== "none") || ch.traits[0];
    const st = ch.status === "dead" ? `Dead · EP${ch.status_since_episode}` : ch.status === "alive" ? "Alive" : "Unknown";
    return `<div class="fact"><span class="who">${esc(ch.name)}</span><span class="pill ${esc(ch.status)}">${esc(st)}</span>
      ${t ? `<span class="desc">${esc(t.name)}: ${esc(t.value.slice(0, 90))}</span>` : ""}</div>`;
  }).join("");
}

function refFor(label) {
  const r = (state.canon?.references || []).find((x) => x.label.toLowerCase() === (label || "").toLowerCase());
  return r ? r.asset : "";
}

/* ---------- session ---------- */
function openFindings(r) { return (r?.findings || []).filter((f) => f.status === "open"); }

function renderScore() {
  const r = state.session.report;
  const meter = $("scoremeter");
  meter.classList.remove("bad", "good");
  const ship = $("btnShip");
  ship.classList.remove("ready", "done");
  if (!r) {
    $("score").textContent = "—";
    $("checks").textContent = "not verified yet";
    ship.disabled = true;
    ship.querySelector(".lock").textContent = "🔒";
    $("shipTxt").textContent = "Ship locked · not verified";
    $("btnMemo").disabled = true;
    return;
  }
  $("score").textContent = r.score;
  meter.classList.add(r.shippable && r.score === 100 ? "good" : r.shippable ? "good" : "bad");
  $("checks").textContent = `${r.checks_passed} / ${r.checks_total} checks passed${r.checks_failed ? ` · ${r.checks_failed} errored` : ""}`;
  $("btnMemo").disabled = state.busy;
  const crit = openFindings(r).filter((f) => f.severity === "critical").length;
  if (state.session.shipped_at) {
    ship.classList.add("done"); ship.disabled = true;
    ship.querySelector(".lock").textContent = "✓";
    $("shipTxt").textContent = "Chapter shipped";
  } else if (r.shippable) {
    ship.classList.add("ready"); ship.disabled = state.busy;
    ship.querySelector(".lock").textContent = "可";
    $("shipTxt").textContent = "Ship chapter";
  } else {
    ship.disabled = true;
    ship.querySelector(".lock").textContent = "🔒";
    $("shipTxt").textContent = `Ship locked · ${crit} critical`;
  }
}

function renderPanels() {
  const d = state.session.draft;
  const r = state.session.report;
  $("eptitle").textContent = `EP${d.episode}${d.title ? " — " + d.title : ""}`;
  $("pcount").textContent = `${d.panels.length} panels`;
  const open = openFindings(r);
  const resolved = (r?.findings || []).filter((f) => f.status === "resolved" || f.status === "dismissed");
  $("panels").innerHTML = d.panels.map((p) => {
    const mine = open.filter((f) => f.panel_id === p.id);
    const fixed = resolved.find((f) => f.panel_id === p.id);
    const crit = mine.some((f) => f.severity === "critical");
    const cls = mine.length ? "flagged" : fixed ? "fixed" : "";
    const stat = !r ? "" : mine.length
      ? `<span class="stat ${crit ? "bad" : "warn"}">✕ ${crit ? "Continuity break" : "Warning"}</span>`
      : `<span class="stat ok">✓ ${fixed ? (fixed.status === "dismissed" ? "Editor approved" : "Fixed") : "Consistent"}</span>`;
    const regen = fixed && fixed.regenerated_image && fixed.status === "resolved" ? fixed.regenerated_image : "";
    const img = regen || p.image;
    return `<div class="pcard ${cls}" data-panel="${esc(p.id)}">${mine.length ? '<div class="cornerseal"></div>' : ""}
      <div class="ptop"><span class="pn">PANEL <b>${p.index}</b></span>${stat}</div>
      ${img ? `<img class="pimg" src="${assetUrl(img)}" alt="">` : `<div class="noimg">no art attached</div>`}
      <div class="pcap">${esc(p.caption)}${p.dialogue ? `<div class="dl">❝ ${esc(p.dialogue)}</div>` : ""}</div></div>`;
  }).join("");
  for (const el of document.querySelectorAll(".pcard[data-panel]")) {
    el.onclick = () => {
      const f = (r?.findings || []).find((x) => x.panel_id === el.dataset.panel && x.status !== "rejected");
      if (f) { state.selected = f.id; renderFindings(); }
    };
  }
}

function renderFindings() {
  const r = state.session.report;
  if (!r) { $("ftabs").innerHTML = ""; $("detail").innerHTML = ""; $("fcount").textContent = ""; return; }
  const shown = r.findings.filter((f) => f.status !== "rejected");
  const rejected = r.findings.filter((f) => f.status === "rejected");
  $("fcount").textContent = `${openFindings(r).length} open · ${shown.length - openFindings(r).length} closed${rejected.length ? ` · ${rejected.length} overruled` : ""}`;
  if (!shown.length) {
    $("ftabs").innerHTML = rejected.length ? overruledHtml(rejected) : "";
    $("detail").innerHTML = `<div class="empty-ok">No continuity breaks found — this chapter is consistent with the canon.</div>`;
    return;
  }
  if (!shown.find((f) => f.id === state.selected)) state.selected = (openFindings(r)[0] || shown[0]).id;
  $("ftabs").innerHTML = shown.map((f, i) => {
    const res = f.status !== "open";
    return `<button class="ftab ${f.id === state.selected ? "sel" : ""} ${res ? "res" : ""}" data-id="${esc(f.id)}">
      <div class="fk">#${i + 1} · ${esc(f.dimension)} · ${res ? esc(f.status) : esc(f.severity)}</div>
      <div class="ft">${esc(f.title)}</div></button>`;
  }).join("") + (rejected.length ? overruledHtml(rejected) : "");
  for (const b of document.querySelectorAll(".ftab")) b.onclick = () => { state.selected = b.dataset.id; renderFindings(); };
  renderDetail(shown.find((f) => f.id === state.selected), shown.indexOf(shown.find((f) => f.id === state.selected)) + 1);
}

function overruledHtml(rej) {
  return `<details class="overruled" style="width:100%"><summary>Overruled by Argon (${rej.length}) — subagent flags rejected after cross-checking the full series</summary>
    ${rej.map((f) => `<p><b>${esc(f.title)}</b> — ${esc(f.adjudication?.rationale || "")}</p>`).join("")}</details>`;
}

function renderDetail(f, n) {
  if (!f) { $("detail").innerHTML = ""; return; }
  const panel = state.session.draft.panels.find((p) => p.id === f.panel_id);
  const res = f.status !== "open";
  const adj = f.adjudication;
  let evidence = "";
  if (f.dimension === "appearance") {
    const canonImg = refFor(f.reference_label);
    const three = !!f.regenerated_image;
    evidence = `<div class="evidence ${three ? "three" : ""}">
      ${canonImg ? `<div class="ev canon"><div class="evtop"><span>Canon authority</span><span>${esc(f.reference_label)}</span></div><img src="${assetUrl(canonImg)}" alt=""></div>` : ""}
      ${three ? "" : `<div class="vs"><span>≠</span>MISMATCH</div>`}
      ${panel?.image ? `<div class="ev draft"><div class="evtop"><span>Submitted draft</span><span>${esc(f.panel_ref)}</span></div><img src="${assetUrl(panel.image)}" alt=""></div>` : ""}
      ${three ? `<div class="ev regen"><div class="evtop"><span>Regenerated</span><span>attempt ${f.regen_attempts}</span></div><img src="${assetUrl(f.regenerated_image)}" alt=""></div>` : ""}
    </div>`;
  }
  const mm = f.mismatches?.length ? `<table class="mm"><tr><th>Trait</th><th>Canon</th><th>Draft</th></tr>
    ${f.mismatches.map((m) => `<tr><td>${esc(m.trait)}</td><td>${esc(m.canon)}</td><td>${esc(m.draft)}</td></tr>`).join("")}</table>` : "";
  const adjHtml = adj ? `<div class="note adj"><div class="nl">Argon adjudicator · ${esc(adj.verdict.replace("_", " "))}</div>
    ${adj.evidence_quote ? `<p>Canon evidence · EP${adj.evidence_episode}: <q>${esc(adj.evidence_quote)}</q></p>` : ""}
    ${adj.rationale ? `<p style="color:var(--muted);font-size:12.5px;margin-top:6px">${esc(adj.rationale)}</p>` : ""}</div>` : "";
  let actions = "";
  if (!res && !state.session.shipped_at) {
    if (f.can_regenerate) {
      actions = `<button class="cta" data-act="regen"><span>✦</span> Regenerate &amp; re-verify</button>
        <button class="ghost" data-act="dismiss">Dismiss — intentional</button>
        <div class="hint">closed loop · ${esc(state.health?.models?.image || "image model")}<br>re-verified by a vision agent · ≤3 tries</div>`;
    } else {
      actions = `<button class="cta" data-act="dismiss"><span>✓</span> Dismiss — intentional</button>
        <button class="ghost" data-act="keep">Keep flagged</button>
        <div class="hint">story judgement stays with the editor<br>human-in-the-loop</div>`;
    }
  } else if (res) {
    actions = f.decision ? `<div class="resnote">Editor decision: ${esc(f.decision.action)}${f.decision.note ? " — " + esc(f.decision.note) : ""}</div>` : "";
  }
  $("detail").innerHTML = `<div class="detail ${res ? "res" : ""}">
    <div class="dhead"><span class="fid">#${n}</span><span class="dt">${esc(f.title)}</span>
      <span class="sev">${esc(f.dimension)} · ${res ? esc(f.status) : esc(f.severity)}${f.needs_human && !res ? " · editor call" : ""}</span></div>
    <div class="dbody">${evidence}
      ${f.resolution_note ? `<div class="resnote">${res ? "✓ " : "⚠ "}${esc(f.resolution_note)}</div>` : ""}
      <div class="note"><div class="nl">${esc(f.agent)} agent · ${esc(f.panel_ref)} vs ${esc(f.canon_ref)}</div><p>${esc(f.explanation)}</p></div>
      ${adjHtml}${mm}
      <div class="fix"><span class="fl">Suggested fix</span><span>${esc(f.suggested_fix)}</span></div>
      <div class="dactions">${actions}</div></div></div>`;
  for (const b of $("detail").querySelectorAll("[data-act]")) b.onclick = () => act(f, b.dataset.act);
}

function renderAll() {
  renderScore(); renderPanels(); renderFindings();
  for (const id of ["btnVerify", "btnNew", "btnEdit"]) $(id).disabled = state.busy;
  for (const b of document.querySelectorAll("[data-act]")) b.disabled = state.busy;
}

/* ---------- actions ---------- */
async function withRun(label, fn) {
  if (state.busy) return;
  state.busy = true; renderAll();
  const runId = crypto.randomUUID();
  const stop = startTrace(runId, label);
  try { await fn(runId); }
  catch (e) { toast(e.message); }
  finally { await stop(); state.busy = false; renderAll(); }
}

async function verify() {
  await withRun("Verification", async (runId) => {
    const report = await api("POST", `/api/sessions/${state.session.session_id}/verify`, { run_id: runId });
    state.session.report = report; state.session.shipped_at = 0; state.selected = null;
  });
}

async function act(f, a) {
  const sid = state.session.session_id;
  if (a === "regen") {
    await withRun("Regeneration", async (runId) => {
      state.session.report = await api("POST", `/api/sessions/${sid}/findings/${f.id}/regenerate`, { run_id: runId });
    });
    return;
  }
  try {
    const note = a === "dismiss" ? (f.can_regenerate ? "Intentional art choice" : "Intentional — framed as a vision/flashback") : "";
    state.session.report = await api("POST", `/api/sessions/${sid}/findings/${f.id}/decision`, { action: a, note });
    renderAll();
  } catch (e) { toast(e.message); }
}

async function ship() {
  try {
    state.session = await api("POST", `/api/sessions/${state.session.session_id}/ship`);
    renderAll();
    $("stamp").classList.remove("hidden");
    setTimeout(() => $("stamp").classList.add("hidden"), 2600);
  } catch (e) { toast(e.message); }
}

async function memo() {
  await withRun("Editor memo", async (runId) => {
    const { memo } = await api("POST", `/api/sessions/${state.session.session_id}/memo`, { run_id: runId });
    $("mtitle").textContent = `Editor memo · EP${state.session.draft.episode}`;
    $("mbody").innerHTML = md(memo);
    $("modal").classList.remove("hidden");
  });
}

function md(src) {
  const lines = src.split("\n"); let html = ""; let list = null;
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const l of lines) {
    let m;
    if ((m = l.match(/^(#{1,3})\s+(.*)/))) { close(); html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; }
    else if ((m = l.match(/^\s*[-*]\s+(.*)/))) { if (list !== "ul") { close(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = l.match(/^\s*\d+\.\s+(.*)/))) { if (list !== "ol") { close(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = l.match(/^>\s?(.*)/))) { close(); html += `<blockquote>${inline(m[1])}</blockquote>`; }
    else if (l.trim()) { close(); html += `<p>${inline(l)}</p>`; }
    else close();
  }
  close(); return html;
}

async function newSession() {
  try {
    state.session = await api("POST", "/api/sessions", { canon_id: "demo" });
    state.selected = null;
    $("trace").innerHTML = `<div class="empty">Run verification to watch Argon plan, delegate to parallel agents and adjudicate — live.</div>`;
    $("runstate").textContent = "idle";
    renderAll();
  } catch (e) { toast(e.message); }
}

/* ---------- edit drawer ---------- */
function openDrawer() {
  state.edit = JSON.parse(JSON.stringify(state.session.draft));
  state.edit.panels.forEach((p) => (p._orig = p.caption + "|" + p.dialogue + "|" + p.image));
  renderDrawer();
  $("dim").classList.remove("hidden"); $("drawer").classList.remove("hidden");
}
function closeDrawer() { $("dim").classList.add("hidden"); $("drawer").classList.add("hidden"); }

function renderDrawer() {
  $("dwBody").innerHTML = state.edit.panels.map((p, i) => {
    const edited = p._orig !== p.caption + "|" + p.dialogue + "|" + p.image;
    return `<div class="ep ${edited ? "edited" : ""}">
      <div class="th">${p.image ? `<img src="${assetUrl(p.image)}" alt="">` : `<div class="noimg">no art</div>`}
        <label class="rep">↑ Replace image<input type="file" accept="image/png,image/jpeg,image/webp" data-i="${i}" hidden></label></div>
      <div class="f"><div class="row"><span class="pn">PANEL <b>${i + 1}</b></span><button class="del" data-del="${i}">✕ remove</button></div>
        <span class="label">Caption</span><textarea data-i="${i}" data-k="caption">${esc(p.caption)}</textarea>
        <span class="label">Dialogue</span><textarea data-i="${i}" data-k="dialogue">${esc(p.dialogue)}</textarea></div></div>`;
  }).join("");
  for (const t of $("dwBody").querySelectorAll("textarea")) t.oninput = () => {
    state.edit.panels[+t.dataset.i][t.dataset.k] = t.value;
    const p = state.edit.panels[+t.dataset.i];
    t.closest(".ep").classList.toggle("edited", p._orig !== p.caption + "|" + p.dialogue + "|" + p.image);
  };
  for (const inp of $("dwBody").querySelectorAll("input[type=file]")) inp.onchange = async () => {
    const file = inp.files[0]; if (!file) return;
    try {
      const dataUrl = await downscale(file);
      const { ref } = await api("POST", "/api/assets", { data_url: dataUrl });
      state.edit.panels[+inp.dataset.i].image = ref;
      renderDrawer();
    } catch (e) { toast(e.message); }
  };
  for (const b of $("dwBody").querySelectorAll("[data-del]")) b.onclick = () => { state.edit.panels.splice(+b.dataset.del, 1); renderDrawer(); };
}

async function downscale(file, max = 1024) {
  const img = await createImageBitmap(file);
  const s = Math.min(1, max / Math.max(img.width, img.height));
  const c = document.createElement("canvas");
  c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

async function saveDraft() {
  const draft = {
    episode: state.edit.episode, title: state.edit.title,
    panels: state.edit.panels.map((p, i) => ({ id: p.id || `p${i + 1}`, index: i + 1, image: p.image || "", caption: p.caption || "", dialogue: p.dialogue || "" })),
  };
  const ids = new Set(); draft.panels.forEach((p, i) => { if (ids.has(p.id)) p.id = `p${i + 1}x`; ids.add(p.id); });
  try {
    state.session = await api("PUT", `/api/sessions/${state.session.session_id}/draft`, { draft });
    closeDrawer(); renderAll();
    await verify();
  } catch (e) { toast(e.message); }
}

/* ---------- boot ---------- */
async function boot() {
  $("btnVerify").onclick = verify;
  $("btnNew").onclick = newSession;
  $("btnShip").onclick = ship;
  $("btnMemo").onclick = memo;
  $("btnEdit").onclick = openDrawer;
  $("dwCancel").onclick = closeDrawer;
  $("dim").onclick = closeDrawer;
  $("dwSave").onclick = saveDraft;
  $("dwAdd").onclick = () => { state.edit.panels.push({ id: `p${Date.now() % 100000}`, caption: "", dialogue: "", image: "", _orig: "" }); renderDrawer(); };
  $("mclose").onclick = () => $("modal").classList.add("hidden");
  try {
    const [health, canon, session] = await Promise.all([
      api("GET", "/api/health"), api("GET", "/api/canons/demo"), api("POST", "/api/sessions", { canon_id: "demo" }),
    ]);
    state.health = health; state.canon = canon; state.session = session;
    renderCanon(); renderAll();
  } catch (e) { toast("Failed to load: " + e.message); }
}
boot();

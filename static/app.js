const $ = (id) => document.getElementById(id);

// =========================================================================
// Small utilities
// =========================================================================

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  return res;
}

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (kind ? " " + kind : "");
  show(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => hide(t), 2600);
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch { return ""; }
}

// =========================================================================
// Auth gate + view router
// =========================================================================

const views = ["login", "app", "admin"];
function setView(name) {
  for (const v of views) { if (v === name) show($(v)); else hide($(v)); }
}

let me = null; // {username, is_admin}

async function bootstrap() {
  try {
    const res = await api("/api/me");
    if (res.ok) {
      me = await res.json();
      return enterApp();
    }
  } catch { /* ignore, show login */ }
  setView("login");
}

function enterApp() {
  $("userName").textContent = me.username;
  $("userAvatar").textContent = me.username.slice(0, 2);
  if (me.is_admin) show($("adminLink")); else hide($("adminLink"));
  setView("app");
  switchTab("create");
  loadTemplates();
}

// ---- login form ----
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("loginError");
  hide(err);
  $("loginBtn").disabled = true;
  const res = await api("/api/login", {
    method: "POST",
    body: JSON.stringify({ username: $("loginUser").value, password: $("loginPass").value }),
  });
  $("loginBtn").disabled = false;
  if (!res.ok) {
    err.textContent = "Invalid username or password.";
    show(err);
    $("loginPass").value = "";
    return;
  }
  me = await res.json();
  $("loginPass").value = "";
  enterApp();
});

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  me = null;
  setView("login");
});

$("adminLink").addEventListener("click", (e) => { e.preventDefault(); openAdmin(); });
$("backToApp").addEventListener("click", (e) => { e.preventDefault(); setView("app"); });

// ---- tabs ----
function switchTab(name) {
  for (const b of document.querySelectorAll(".tabs button")) {
    b.classList.toggle("active", b.dataset.tab === name);
  }
  show($("tab-create"));
  show($("tab-library"));
  if (name === "create") hide($("tab-library"));
  if (name === "library") { hide($("tab-create")); loadVideos(); }
}
for (const b of document.querySelectorAll(".tabs button")) {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
}

// =========================================================================
// Create tab — 3-step wizard: Details → Caption → Render
// =========================================================================

let currentStep = 1;
let captionReady = false;  // true once AI has drafted (informational; the gate is JSON validity)
let currentJobId = null;

// Returns true if the caption box holds parseable JSON. This is the step-2 gate
// for the Next button: a user can hand-write valid JSON to skip the AI call.
function captionJsonValid() {
  try { JSON.parse($("copyJson").value); return true; }
  catch { return false; }
}
let pollTimer = null;

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  $("template").innerHTML = "";
  for (const name of data.templates) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    $("template").appendChild(opt);
  }
  syncBundleVisibility();
}

function gotoStep(n) {
  currentStep = Math.max(1, Math.min(3, n));
  for (const s of [1, 2, 3]) {
    $(`step-${s}`).classList.toggle("hidden", s !== currentStep);
  }
  // progress dots: active = current, done = before current
  document.querySelectorAll(".step-dot").forEach((dot) => {
    const s = Number(dot.dataset.step);
    dot.classList.toggle("active", s === currentStep);
    dot.classList.toggle("done", s < currentStep);
  });
  // nav buttons
  $("prevBtn").classList.toggle("hidden", currentStep === 1);
  $("nextBtn").classList.toggle("hidden", currentStep === 3);
  // Next is gated on step 2 by caption JSON validity — either AI-generated
  // or hand-written. Lets users skip the AI call by entering their own JSON.
  $("nextBtn").disabled = (currentStep === 2 && !captionJsonValid());
  // Hints adapt to whether the caption box holds valid JSON yet.
  if (currentStep === 2) {
    const val = $("copyJson").value;
    if (!val) {
      $("copyHint").textContent = "Click “Generate caption” to draft one with AI, or paste your own JSON.";
      $("copyHint").className = "status";
    } else if (captionJsonValid()) {
      $("copyHint").textContent = "Caption JSON is valid — edit freely, then Next.";
      $("copyHint").className = "status ok";
    } else {
      $("copyHint").textContent = "Caption JSON is invalid — fix it or click “Generate caption”.";
      $("copyHint").className = "status err";
    }
  }
  if (currentStep === 3) {
    const ok = captionJsonValid();
    $("copyHint").textContent = ok
      ? "Ready to render — click below."
      : "Caption JSON is invalid — go back and fix it.";
    $("copyHint").className = ok ? "status ok" : "status err";
  }
}

$("prevBtn").addEventListener("click", () => gotoStep(currentStep - 1));
$("nextBtn").addEventListener("click", () => gotoStep(currentStep + 1));

// Live-update the Next-button gate + hint as the user edits the caption box,
// so hand-written valid JSON unlocks Next without an AI call.
$("copyJson").addEventListener("input", () => {
  if (currentStep === 2) gotoStep(2);
});

// Show the brand-assets box only for the lower-third-brand template.
function syncBundleVisibility() {
  const isLtb = $("template").value === "lower-third-brand";
  $("bundleBox").classList.toggle("hidden", !isLtb);
  if (isLtb) loadBundles();
}
$("template").addEventListener("change", syncBundleVisibility);

// ---- Brand asset bundles -------------------------------------------------
let bundles = [];

async function loadBundles() {
  try {
    const res = await fetch("/api/bundles");
    const data = await res.json();
    bundles = data.bundles || [];
  } catch { bundles = []; }
  renderBundles();
}

function renderBundles() {
  const list = $("bundleList");
  list.innerHTML = "";
  if (bundles.length === 0) {
    list.innerHTML = `<div class="bundle-empty">No bundles yet. Upload one to brand your video.</div>`;
    return;
  }
  if (bundles.length > 1) {
    const rnd = document.createElement("label");
    rnd.className = "bundle-row";
    rnd.innerHTML = `<input type="radio" name="bundle" value="random" /><span class="bname">Random (pick any of mine)</span>`;
    list.appendChild(rnd);
  }
  bundles.forEach((b) => {
    const row = document.createElement("label");
    row.className = "bundle-row";
    row.innerHTML = `
      <input type="radio" name="bundle" value="${b.bundle_id}" />
      <span class="bname" title="${b.name}">${b.name}</span>
      <span class="bmeta">${fmtDate(b.created_at)}</span>
      <button type="button" class="btn danger" data-delbundle="${b.bundle_id}">Delete</button>`;
    list.appendChild(row);
  });
  const first = list.querySelector('input[name="bundle"]');
  if (first) first.checked = true;

  list.querySelectorAll("[data-delbundle]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const id = btn.dataset.delbundle;
      if (!confirm("Delete this brand bundle?")) return;
      const res = await fetch(`/api/bundles/${id}`, { method: "DELETE" });
      if (res.ok) { toast("Bundle deleted.", "ok"); await loadBundles(); }
      else { toast("Could not delete bundle.", "err"); }
    });
  });
}

function selectedBundleId() {
  const el = document.querySelector('input[name="bundle"]:checked');
  return el ? el.value : null;
}

$("toggleUploadBtn").addEventListener("click", () => {
  $("uploadForm").classList.toggle("hidden");
});

$("uploadBundleBtn").addEventListener("click", async () => {
  const msg = $("uploadMsg");
  msg.textContent = ""; msg.className = "status";
  const name = $("bundleName").value.trim();
  const bb = $("bottomBarFile").files[0];
  const wm = $("watermarkFile").files[0];
  if (!bb || !wm) { msg.textContent = "Choose both PNG files."; msg.className = "status err"; return; }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("bottom_bar", bb);
  fd.append("watermark", wm);
  $("uploadBundleBtn").disabled = true;
  const res = await fetch("/api/bundles", { method: "POST", body: fd });
  $("uploadBundleBtn").disabled = false;
  if (res.ok) {
    msg.textContent = "Bundle saved."; msg.className = "status ok";
    $("bundleName").value = "";
    $("bottomBarFile").value = "";
    $("watermarkFile").value = "";
    await loadBundles();
  } else {
    const d = await res.json().catch(() => ({}));
    msg.textContent = d.detail || "Upload failed.";
    msg.className = "status err";
  }
});

function formatPref() {
  return document.querySelector('input[name="format"]:checked').value;
}

// ---- Step 2: AI caption --------------------------------------------------
$("previewBtn").addEventListener("click", async () => {
  const hint = $("copyHint");
  hint.textContent = "Generating caption…";
  hint.className = "status";
  $("previewBtn").disabled = true;
  const res = await fetch("/api/preview-copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value, template: $("template").value,
    }),
  });
  $("previewBtn").disabled = false;
  if (!res.ok) {
    hint.textContent = "Caption failed: " + (await res.text());
    hint.className = "status err";
    return;
  }
  const data = await res.json();
  $("copyJson").value = JSON.stringify(data.copy, null, 2);
  captionReady = true;
  hint.textContent = "Caption ready — edit freely, then Next.";
  hint.className = "status ok";
  gotoStep(2);  // refreshes the Next-button gate (now enabled)
});

// ---- Step 3: render + poll ----------------------------------------------
$("renderBtn").addEventListener("click", async () => {
  let copy;
  try { copy = JSON.parse($("copyJson").value); } catch {
    $("status").textContent = "Caption JSON is invalid.";
    $("status").className = "status err";
    return;
  }
  $("renderBtn").disabled = true;
  $("status").textContent = "Starting…";
  $("status").className = "status";
  hide($("cancelBtn"));
  hide($("result"));
  hide($("resetBtn"));

  const bundleId = ($("template").value === "lower-third-brand") ? selectedBundleId() : null;

  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value,
      template: $("template").value, format_pref: formatPref(),
      copy_data: copy,
      clip_keyword: $("clipKeyword").value.trim() || null,
      asset_bundle_id: bundleId,
      include_audio: $("soundToggle").checked,
    }),
  });
  if (!res.ok) {
    $("status").textContent = "Render failed: " + (await res.text());
    $("status").className = "status err";
    $("renderBtn").disabled = false;
    return;
  }
  const data = await res.json();
  currentJobId = data.job_id;
  startPolling();
});

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  show($("cancelBtn"));
  $("cancelBtn").disabled = false;
  pollTimer = setInterval(pollJob, 1500);
  pollJob();
}

async function pollJob() {
  if (!currentJobId) return;
  const res = await fetch(`/api/jobs/${currentJobId}`);
  if (!res.ok) {
    stopPolling();
    $("status").textContent = "Lost contact with job.";
    $("status").className = "status err";
    $("renderBtn").disabled = false;
    return;
  }
  const job = await res.json();
  $("status").textContent = job.progress_message || job.status;
  $("status").className = "status";

  if (job.status === "searching") { $("cancelBtn").disabled = false; return; }
  if (job.status === "rendering") { $("cancelBtn").disabled = true; return; }
  stopPolling();
  hide($("cancelBtn"));
  $("renderBtn").disabled = false;
  show($("resetBtn"));

  if (job.status === "done" && job.result) {
    const filename = job.result.output_path.split("/").pop();
    $("result").src = "/api/files/" + filename + "?t=" + Date.now();
    show($("result"));
    $("status").textContent = "Done: " + filename;
    $("status").className = "status ok";
  } else if (job.status === "cancelled") {
    $("status").textContent = "Cancelled.";
  } else {
    $("status").textContent = "Failed: " + (job.error || "unknown error");
    $("status").className = "status err";
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

$("cancelBtn").addEventListener("click", async () => {
  if (!currentJobId) return;
  $("cancelBtn").disabled = true;
  $("status").textContent = "Cancelling…";
  await fetch(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
});

// Reset the wizard to its initial state (step 1, everything cleared).
$("resetBtn").addEventListener("click", () => {
  $("topic").value = "";
  $("clipKeyword").value = "";
  $("tone").selectedIndex = 0;
  document.querySelector('input[name="format"][value="auto"]').checked = true;
  $("copyJson").value = "";
  captionReady = false;
  hide($("result"));
  hide($("cancelBtn"));
  hide($("resetBtn"));
  $("result").removeAttribute("src");
  $("status").textContent = "";
  $("status").className = "status";
  $("copyHint").textContent = "";
  $("copyHint").className = "status";
  $("previewBtn").disabled = false;
  $("renderBtn").disabled = false;
  currentJobId = null;
  gotoStep(1);
  toast("Ready for a new video.", "ok");
});

// =========================================================================
// Library tab — responsive card grid, download, remove, bulk-delete
// =========================================================================

let videos = [];
const selected = new Set();

async function loadVideos() {
  try {
    const res = await api("/api/videos");
    const data = await res.json();
    videos = data.videos || [];
  } catch {
    videos = [];
  }
  selected.clear();
  renderVideos();
}

function renderVideos() {
  const grid = $("vidGrid");
  $("vidCount").textContent = videos.length;
  grid.innerHTML = "";

  if (videos.length === 0) {
    grid.innerHTML = `
      <div class="empty" style="grid-column:1/-1;">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2"/></svg>
        <div>No videos yet. Create one from the <b>Create</b> tab.</div>
      </div>`;
    updateBulkBar();
    return;
  }

  for (const v of videos) {
    const card = document.createElement("div");
    card.className = "card";
    if (selected.has(v.id)) card.classList.add("selected");

    const safe = v.filename.replace(/"/g, "");
    card.innerHTML = `
      <div class="card-wrap">
        <input type="checkbox" class="card-select" data-id="${v.id}" ${selected.has(v.id) ? "checked" : ""} aria-label="Select video" />
        <video src="${v.url}?t=${Date.now()}" preload="metadata" controls playsinline></video>
      </div>
      <div class="card-body">
        <div class="card-title" title="${v.topic.replace(/"/g, "&quot;")}">${v.topic}</div>
        <div class="card-meta">${fmtDate(v.created_at)}</div>
        <div class="card-actions">
          ${v.url ? `<a class="btn ghost" href="${v.url}" download="${safe}">Download</a>` : ""}
          <button class="btn danger" data-del="${v.id}">Remove</button>
        </div>
      </div>`;
    grid.appendChild(card);
  }

  // wire up controls
  grid.querySelectorAll(".card-select").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.id;
      if (cb.checked) selected.add(id); else selected.delete(id);
      cb.closest(".card").classList.toggle("selected", cb.checked);
      updateBulkBar();
    });
  });
  grid.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Remove this video? It will be deleted from disk.")) return;
      const id = btn.dataset.del;
      const res = await api(`/api/videos/${id}`, { method: "DELETE" });
      if (res.ok) { toast("Video removed.", "ok"); await loadVideos(); }
      else { toast("Could not remove video.", "err"); }
    });
  });

  updateBulkBar();
}

function updateBulkBar() {
  const bar = $("bulkBar");
  $("selCount").textContent = `${selected.size} selected`;
  bar.classList.toggle("hidden", selected.size === 0);
}

$("clearSelBtn").addEventListener("click", () => {
  selected.clear();
  document.querySelectorAll(".card-select").forEach((cb) => { cb.checked = false; cb.closest(".card").classList.remove("selected"); });
  updateBulkBar();
});

$("bulkDeleteBtn").addEventListener("click", async () => {
  const ids = [...selected];
  if (ids.length === 0) return;
  if (!confirm(`Delete ${ids.length} selected video(s)? This cannot be undone.`)) return;
  const res = await api("/api/videos/bulk-delete", {
    method: "POST",
    body: JSON.stringify({ job_ids: ids }),
  });
  if (res.ok) {
    const data = await res.json();
    toast(`Deleted ${data.deleted}.`, "ok");
    await loadVideos();
  } else {
    toast("Bulk delete failed.", "err");
  }
});

// =========================================================================
// Admin tab — list / add / delete users
// =========================================================================

async function openAdmin() {
  if (!me || !me.is_admin) { setView("app"); return; }
  setView("admin");
  await loadUsers();
}

async function loadUsers() {
  const list = $("userList");
  list.innerHTML = `<div style="color:var(--text-dim);">Loading…</div>`;
  try {
    const res = await api("/api/admin/users");
    const data = await res.json();
    const users = data.users || [];
    list.innerHTML = "";
    for (const u of users) {
      const row = document.createElement("div");
      row.className = "user-row";
      row.innerHTML = `
        <span class="badge ${u.is_admin ? "admin" : "user"}">${u.is_admin ? "admin" : "user"}</span>
        <span class="uname">${u.username.replace(/</g, "&lt;")}</span>
        <span class="user-meta">${fmtDate(u.created_at)}</span>
        ${u.username === me.username ? "" : `<button class="btn danger" data-deluser="${u.username}">Delete</button>`}
      `;
      list.appendChild(row);
    }
    list.querySelectorAll("[data-deluser]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const uname = btn.dataset.deluser;
        if (!confirm(`Delete user "${uname}"? They will no longer be able to log in.`)) return;
        const res = await api(`/api/admin/users/${encodeURIComponent(uname)}`, { method: "DELETE" });
        if (res.ok) { toast(`User "${uname}" deleted.`, "ok"); await loadUsers(); }
        else { const d = await res.json().catch(() => ({})); toast(d.detail || "Delete failed.", "err"); }
      });
    });
  } catch {
    list.innerHTML = `<div style="color:var(--danger);">Failed to load users.</div>`;
  }
}

$("addUserForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("addUserMsg");
  const u = $("newUser").value.trim();
  const p = $("newPass").value;
  msg.textContent = ""; msg.className = "status";
  if (!u || !p) { msg.textContent = "Username and password required."; msg.className = "status err"; return; }
  const res = await api("/api/admin/users", {
    method: "POST",
    body: JSON.stringify({ username: u, password: p }),
  });
  if (res.ok) {
    msg.textContent = `Created "${u}".`; msg.className = "status ok";
    $("newUser").value = ""; $("newPass").value = "";
    await loadUsers();
  } else {
    const d = await res.json().catch(() => ({}));
    msg.textContent = d.detail || "Could not add user.";
    msg.className = "status err";
  }
});

// =========================================================================
// Go
// =========================================================================

bootstrap();

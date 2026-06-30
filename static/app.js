const $ = (id) => document.getElementById(id);

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  for (const name of data.templates) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    $("template").appendChild(opt);
  }
}

function formatPref() {
  return document.querySelector('input[name="format"]:checked').value;
}

// ---- Copy preview ----------------------------------------------------------

$("previewBtn").addEventListener("click", async () => {
  $("status").textContent = "Generating copy…";
  const res = await fetch("/api/preview-copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value, template: $("template").value,
    }),
  });
  if (!res.ok) { $("status").textContent = "Copy failed: " + (await res.text()); return; }
  const data = await res.json();
  $("copyJson").value = JSON.stringify(data.copy, null, 2);
  $("copyBox").classList.remove("hidden");
  $("status").textContent = "Copy ready — edit if you like, then render.";
});

// ---- Render (async job + polling) -----------------------------------------

let currentJobId = null;
let pollTimer = null;

$("renderBtn").addEventListener("click", async () => {
  let copy;
  try { copy = JSON.parse($("copyJson").value); } catch (e) {
    $("status").textContent = "Copy JSON is invalid.";
    return;
  }
  $("renderBtn").disabled = true;
  $("status").textContent = "Starting…";
  $("cancelBtn").classList.add("hidden");
  $("result").classList.add("hidden");

  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value,
      template: $("template").value, format_pref: formatPref(),
      copy_data: copy,
      clip_keyword: $("clipKeyword").value.trim() || null,
    }),
  });
  if (!res.ok) {
    $("status").textContent = "Render failed: " + (await res.text());
    $("renderBtn").disabled = false;
    return;
  }
  const data = await res.json();
  currentJobId = data.job_id;
  startPolling();
});

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  $("cancelBtn").classList.remove("hidden");
  $("cancelBtn").disabled = false;
  pollTimer = setInterval(pollJob, 1500);
  pollJob(); // immediate first poll
}

async function pollJob() {
  if (!currentJobId) return;
  const res = await fetch(`/api/jobs/${currentJobId}`);
  if (!res.ok) {
    stopPolling();
    $("status").textContent = "Lost contact with job.";
    $("renderBtn").disabled = false;
    return;
  }
  const job = await res.json();
  $("status").textContent = job.progress_message || job.status;

  if (job.status === "searching") {
    $("cancelBtn").disabled = false;
    return; // keep polling
  }
  if (job.status === "rendering") {
    $("cancelBtn").disabled = true;     // render phase is not interruptible
    return;
  }
  // Terminal state.
  stopPolling();
  $("cancelBtn").classList.add("hidden");
  $("renderBtn").disabled = false;

  if (job.status === "done" && job.result) {
    const filename = job.result.output_path.split("/").pop();
    $("result").src = "/api/files/" + filename + "?t=" + Date.now();
    $("result").classList.remove("hidden");
    $("status").textContent = "Done: " + filename;
  } else if (job.status === "cancelled") {
    $("status").textContent = "Cancelled.";
  } else { // failed
    $("status").textContent = "Failed: " + (job.error || "unknown error");
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
  // polling continues; the worker will set status=cancelled and we stop then
});

loadTemplates();

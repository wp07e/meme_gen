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

$("renderBtn").addEventListener("click", async () => {
  $("status").textContent = "Rendering… (this takes ~20-40s)";
  let copy;
  try { copy = JSON.parse($("copyJson").value); } catch (e) {
    $("status").textContent = "Copy JSON is invalid.";
    return;
  }
  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value,
      template: $("template").value, source: $("source").value, copy_data: copy,
    }),
  });
  if (!res.ok) { $("status").textContent = "Render failed: " + (await res.text()); return; }
  const data = await res.json();
  const filename = data.output_path.split("/").pop();
  $("result").src = "/api/files/" + filename;
  $("result").classList.remove("hidden");
  $("status").textContent = "Done: " + filename;
});

loadTemplates();

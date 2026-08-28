"use strict";

// Poll interval for live job progress (ms).
const POLL_MS = 1000;

const form = document.getElementById("job-form");
const jobsEl = document.getElementById("jobs");
const errEl = document.getElementById("err");
const startBtn = document.getElementById("start");

// Local cache of the last-known job dicts, keyed by id.
const jobs = new Map();

function pct(job) {
  const p = typeof job.progress === "number" ? job.progress : 0;
  return Math.max(0, Math.min(100, Math.round(p * 100)));
}

function statusClass(status) {
  if (status === "done") return "status done";
  if (status === "error" || status === "failed") return "status error";
  return "status";
}

function renderJob(job) {
  let li = document.getElementById("job-" + job.id);
  if (!li) {
    li = document.createElement("li");
    li.id = "job-" + job.id;
    li.className = "job";
    jobsEl.prepend(li);
  }
  const stage = job.stage ? " \u00b7 " + job.stage : "";
  const done = job.status === "done";
  const failed = job.status === "error" || job.status === "failed";
  li.innerHTML = "";

  const head = document.createElement("div");
  head.className = "head";
  const src = document.createElement("span");
  src.className = "src";
  src.textContent = job.source || job.id;
  const st = document.createElement("span");
  st.className = statusClass(job.status);
  st.textContent = (job.status || "queued") + stage;
  head.append(src, st);

  const bar = document.createElement("div");
  bar.className = "bar";
  const fill = document.createElement("span");
  fill.style.width = pct(job) + "%";
  bar.append(fill);

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = "id: " + job.id + " \u00b7 " + pct(job) + "%";

  li.append(head, bar, meta);

  if (done) {
    const a = document.createElement("a");
    a.className = "dl";
    a.href = "/api/jobs/" + job.id + "/download";
    a.textContent = "\u2b07 Download mp4";
    li.append(a);
  }
  if (failed && job.error) {
    const e = document.createElement("div");
    e.className = "errmsg";
    e.textContent = job.error;
    li.append(e);
  }
}

function isActive(job) {
  return job.status !== "done" && job.status !== "error" && job.status !== "failed";
}

async function refresh() {
  try {
    const res = await fetch("/api/jobs");
    if (!res.ok) return;
    const list = await res.json();
    for (const job of list) {
      jobs.set(job.id, job);
      renderJob(job);
    }
  } catch (e) {
    // Ignore transient poll errors; next tick retries.
  }
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  if (!res.ok) throw new Error("upload failed (" + res.status + ")");
  const data = await res.json();
  return data.source;
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errEl.textContent = "";
  startBtn.disabled = true;
  try {
    let source = document.getElementById("source").value.trim();
    const fileInput = document.getElementById("file");
    if (fileInput.files && fileInput.files.length > 0) {
      source = await uploadFile(fileInput.files[0]);
    }
    if (!source) {
      throw new Error("Enter a URL/path or choose a file.");
    }
    const body = {
      source: source,
      fps: parseInt(document.getElementById("fps").value, 10) || 30,
      hands: document.getElementById("hands").checked,
      key_tempo: document.getElementById("key_tempo").checked,
      separate: document.getElementById("separate").checked,
    };
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status !== 202 && !res.ok) {
      throw new Error("submit failed (" + res.status + ")");
    }
    const job = await res.json();
    jobs.set(job.id, job);
    renderJob(job);
    form.reset();
    document.getElementById("fps").value = 30;
  } catch (e) {
    errEl.textContent = e.message || String(e);
  } finally {
    startBtn.disabled = false;
  }
});

refresh();
setInterval(refresh, POLL_MS);

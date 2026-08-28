"use strict";

// Poll interval for live job progress (ms).
const POLL_MS = 1000;

const form = document.getElementById("job-form");
const jobsEl = document.getElementById("jobs");
const errEl = document.getElementById("err");
const startBtn = document.getElementById("start");
const emptyEl = document.getElementById("empty");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file");
const filenameEl = document.getElementById("filename");
const clearBtn = document.getElementById("clear-finished");

// Local cache of the last-known job dicts, keyed by id.
const jobs = new Map();
// Ids removed client-side via "Clear finished"; never re-rendered.
const hidden = new Set();
// A pre-uploaded source path (from drag-drop), if any.
let uploadedSource = null;

function pct(job) {
  const p = typeof job.progress === "number" ? job.progress : 0;
  return Math.max(0, Math.min(100, Math.round(p * 100)));
}

function statusClass(status) {
  if (status === "done") return "status done";
  if (status === "error" || status === "failed") return "status error";
  return "status";
}

function isActive(job) {
  return job.status !== "done" && job.status !== "error" && job.status !== "failed";
}

function fmtDuration(secs) {
  if (typeof secs !== "number" || !isFinite(secs) || secs < 0) return "";
  const s = Math.round(secs);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? m + "m " + r + "s" : r + "s";
}

// Elapsed/duration text derived from created_at/started_at/finished_at.
// Degrades gracefully when a field is missing.
function timing(job) {
  const now = Date.now() / 1000;
  if (job.status === "done" || job.status === "error" || job.status === "failed") {
    if (typeof job.started_at === "number" && typeof job.finished_at === "number") {
      return "took " + fmtDuration(job.finished_at - job.started_at);
    }
    if (typeof job.created_at === "number" && typeof job.finished_at === "number") {
      return "took " + fmtDuration(job.finished_at - job.created_at);
    }
    return "";
  }
  const base = typeof job.started_at === "number" ? job.started_at
    : (typeof job.created_at === "number" ? job.created_at : null);
  if (base === null) return "";
  return "elapsed " + fmtDuration(now - base);
}

async function cancelJob(job) {
  try {
    const res = await fetch("/api/jobs/" + job.id, { method: "DELETE" });
    if (!res.ok) return;
    const updated = await res.json();
    jobs.set(updated.id, updated);
    // If the backend still shows it active, it couldn't be cancelled.
    updated._cancelNote = isActive(updated)
      ? "cannot cancel a running job" : null;
    renderJob(updated);
  } catch (e) {
    // Ignore transient errors; next poll refreshes.
  }
}

function updateEmptyState() {
  const visible = jobsEl.querySelectorAll("li.job").length;
  emptyEl.style.display = visible === 0 ? "block" : "none";
}

function renderJob(job) {
  if (hidden.has(job.id)) return;
  let li = document.getElementById("job-" + job.id);
  if (!li) {
    li = document.createElement("li");
    li.id = "job-" + job.id;
    li.className = "job";
    jobsEl.prepend(li);
  }
  const done = job.status === "done";
  const failed = job.status === "error" || job.status === "failed";
  const active = isActive(job);
  li.innerHTML = "";

  const head = document.createElement("div");
  head.className = "head";
  const src = document.createElement("span");
  src.className = "src";
  src.textContent = job.source || job.id;
  const st = document.createElement("span");
  st.className = statusClass(job.status);
  st.textContent = job.status || "queued";
  head.append(src, st);

  const bar = document.createElement("div");
  bar.className = "bar";
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.setAttribute("aria-valuenow", String(pct(job)));
  const fill = document.createElement("span");
  fill.style.width = pct(job) + "%";
  const label = document.createElement("em");
  label.className = "bar-label";
  const stageTxt = job.stage ? job.stage : (job.status || "queued");
  label.textContent = stageTxt + " \u00b7 " + pct(job) + "%";
  bar.append(fill, label);

  const meta = document.createElement("div");
  meta.className = "meta";
  const t = timing(job);
  meta.textContent = "id: " + job.id + (t ? " \u00b7 " + t : "");

  li.append(head, bar, meta);

  const actions = document.createElement("div");
  actions.className = "actions";

  if (active) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ghost cancel";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => cancelJob(job));
    actions.append(cancel);
  }

  if (done) {
    const a = document.createElement("a");
    a.className = "dl";
    a.href = "/api/jobs/" + job.id + "/download";
    a.textContent = "\u2b07 Download mp4";
    actions.append(a);
  }
  if (actions.childElementCount > 0) li.append(actions);

  if (done) {
    const vid = document.createElement("video");
    vid.className = "preview";
    vid.controls = true;
    vid.preload = "metadata";
    vid.src = "/api/jobs/" + job.id + "/download";
    li.append(vid);
  }

  if (job._cancelNote) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = job._cancelNote;
    li.append(note);
  }
  if (failed && job.error) {
    const e = document.createElement("div");
    e.className = "errmsg";
    e.textContent = job.error;
    li.append(e);
  }
  updateEmptyState();
}

async function refresh() {
  try {
    const res = await fetch("/api/jobs");
    if (!res.ok) return;
    const list = await res.json();
    for (const job of list) {
      if (hidden.has(job.id)) continue;
      const prev = jobs.get(job.id);
      if (prev && prev._cancelNote) job._cancelNote = prev._cancelNote;
      jobs.set(job.id, job);
      renderJob(job);
    }
    updateEmptyState();
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

async function handleDroppedFile(file) {
  errEl.textContent = "";
  filenameEl.textContent = "uploading " + file.name + "\u2026";
  try {
    uploadedSource = await uploadFile(file);
    filenameEl.textContent = "\u2713 " + file.name;
  } catch (e) {
    uploadedSource = null;
    filenameEl.textContent = "";
    errEl.textContent = e.message || String(e);
  }
}

// Drag-and-drop wiring on the dropzone (whole card region).
["dragenter", "dragover"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  });
});
dropzone.addEventListener("drop", (e) => {
  const files = e.dataTransfer && e.dataTransfer.files;
  if (files && files.length > 0) handleDroppedFile(files[0]);
});
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files && fileInput.files.length > 0) {
    handleDroppedFile(fileInput.files[0]);
  }
});

clearBtn.addEventListener("click", () => {
  for (const [id, job] of jobs) {
    if (!isActive(job)) {
      hidden.add(id);
      const li = document.getElementById("job-" + id);
      if (li) li.remove();
    }
  }
  updateEmptyState();
});

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errEl.textContent = "";
  startBtn.disabled = true;
  const origLabel = startBtn.textContent;
  startBtn.textContent = "Starting\u2026";
  try {
    let source = document.getElementById("source").value.trim();
    if (fileInput.files && fileInput.files.length > 0) {
      source = uploadedSource || (await uploadFile(fileInput.files[0]));
    } else if (uploadedSource) {
      source = uploadedSource;
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
    uploadedSource = null;
    filenameEl.textContent = "";
  } catch (e) {
    errEl.textContent = e.message || String(e);
  } finally {
    startBtn.disabled = false;
    startBtn.textContent = origLabel;
  }
});

updateEmptyState();
refresh();
setInterval(refresh, POLL_MS);

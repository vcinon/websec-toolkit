/* Live scan console backed by Server-Sent Events. */
(function () {
  "use strict";

  const card = document.getElementById("console-card");
  if (!card) return;

  const output = document.getElementById("console-output");
  const statusEl = document.getElementById("console-status");
  const linesEl = document.getElementById("console-lines");
  const hitsEl = document.getElementById("console-hits");
  const errorsEl = document.getElementById("console-errors");
  const elapsedEl = document.getElementById("console-elapsed");
  const pauseButton = document.getElementById("console-pause");
  const stopButton = document.getElementById("console-stop");
  const openLink = document.getElementById("console-open");

  let source = null;
  let scanId = null;
  let counters = { lines: 0, hits: 0, errors: 0 };
  let startedAt = null;
  let timer = null;
  let paused = false;

  const HIT_PATTERN = /\[Status:\s*\d+|^https?:\/\//i;
  const ERROR_PATTERN = /error|failed|refused|timeout/i;

  function append(line) {
    const div = document.createElement("div");
    div.textContent = line; // textContent escapes tool output
    if (line.startsWith("[toolkit]")) {
      div.className = "line-meta";
    } else if (HIT_PATTERN.test(line)) {
      div.className = "line-hit";
      counters.hits += 1;
    } else if (ERROR_PATTERN.test(line)) {
      div.className = "line-error";
      counters.errors += 1;
    }
    counters.lines += 1;
    const atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 60;
    output.appendChild(div);
    while (output.childElementCount > 4000) output.removeChild(output.firstChild);
    if (atBottom) output.scrollTop = output.scrollHeight;
    linesEl.textContent = counters.lines;
    hitsEl.textContent = counters.hits;
    errorsEl.textContent = counters.errors;
  }

  function tick() {
    if (!startedAt) return;
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    elapsedEl.textContent = `Elapsed: ${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }

  function finish(status) {
    statusEl.textContent = status;
    statusEl.className = `status status-${status.toLowerCase()}`;
    if (source) source.close();
    source = null;
    if (timer) clearInterval(timer);
    pauseButton.disabled = true;
    stopButton.disabled = true;
  }

  function attach(id, toolName) {
    scanId = id;
    counters = { lines: 0, hits: 0, errors: 0 };
    output.textContent = "";
    card.hidden = false;
    card.dataset.scanId = id;
    startedAt = Date.now();
    paused = false;
    pauseButton.disabled = false;
    stopButton.disabled = false;
    pauseButton.textContent = "Pause";
    statusEl.textContent = "RUNNING";
    statusEl.className = "status status-running";
    if (toolName) document.getElementById("console-tool").textContent = toolName;
    openLink.href = `/scans/${id}`;
    if (timer) clearInterval(timer);
    timer = setInterval(tick, 1000);

    source = new EventSource(`/api/scans/${id}/stream`);
    source.addEventListener("line", (event) => append(JSON.parse(event.data).line));
    source.addEventListener("exit", () => {
      window.Toolkit.request(`/api/scans/${id}`)
        .then((scan) => finish(scan.status))
        .catch(() => finish("COMPLETED"));
    });
    source.onerror = () => {
      if (source && source.readyState === EventSource.CLOSED) finish("STOPPED");
    };
  }

  pauseButton?.addEventListener("click", async () => {
    if (!scanId) return;
    const endpoint = paused ? "resume" : "pause";
    try {
      await window.Toolkit.request(`/api/scans/${scanId}/${endpoint}`, { method: "POST" });
      paused = !paused;
      pauseButton.textContent = paused ? "Resume" : "Pause";
      statusEl.textContent = paused ? "PAUSED" : "RUNNING";
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    }
  });

  stopButton?.addEventListener("click", async () => {
    if (!scanId) return;
    try {
      await window.Toolkit.request(`/api/scans/${scanId}/stop`, { method: "POST" });
      window.Toolkit.toast("Scan stopped", "success");
      finish("STOPPED");
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    }
  });

  window.ScanConsole = { attach };

  const existing = card.dataset.scanId;
  if (existing) attach(Number(existing), document.getElementById("console-tool")?.textContent);
})();

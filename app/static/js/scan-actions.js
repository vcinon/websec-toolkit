/* Stop / restart / delete / save actions for scan rows and detail pages. */
(function () {
  "use strict";

  const handlers = {
    async stop(id) {
      await window.Toolkit.request(`/api/scans/${id}/stop`, { method: "POST" });
      window.Toolkit.toast(`Scan #${id} stopped`, "success");
      setTimeout(() => window.location.reload(), 600);
    },
    async restart(id) {
      const scan = await window.Toolkit.request(`/api/scans/${id}/restart`, { method: "POST" });
      window.Toolkit.toast(`Restarted as scan #${scan.id}`, "success");
      window.location.href = `/scans/${scan.id}`;
    },
    async delete(id) {
      if (!window.confirm(`Delete scan #${id} and its stored output?`)) return;
      await window.Toolkit.request(`/api/scans/${id}`, { method: "DELETE" });
      window.Toolkit.toast(`Scan #${id} deleted`, "success");
      const row = document.querySelector(`[data-scan-row="${id}"]`);
      if (row) row.remove();
      else window.location.href = "/scans/history";
    },
    async save(id, button) {
      const saved = button.dataset.saved !== "true";
      await window.Toolkit.request(`/api/scans/${id}/save`, { method: "POST", body: { saved } });
      button.dataset.saved = String(saved);
      button.textContent = saved ? "Saved" : "Save scan";
      window.Toolkit.toast(saved ? "Scan saved" : "Scan unsaved", "success");
    },
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action][data-scan-id]");
    if (!button) return;
    const handler = handlers[button.dataset.action];
    if (!handler) return;
    button.disabled = true;
    try {
      await handler(Number(button.dataset.scanId), button);
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    } finally {
      button.disabled = false;
    }
  });
})();

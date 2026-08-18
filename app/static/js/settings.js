/* Re-detect tool binaries without leaving the settings page. */
(function () {
  "use strict";

  document.getElementById("detect-tools")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const statuses = await window.Toolkit.request("/settings/detect", { method: "POST" });
      Object.entries(statuses).forEach(([slug, status]) => {
        const element = document.querySelector(`[data-tool-status="${slug}"]`);
        if (!element) return;
        element.textContent = status.installed
          ? `✓ ${status.path} (${status.version || "unknown version"})`
          : "✗ not found";
      });
      window.Toolkit.toast("Detection finished", "success");
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    } finally {
      button.disabled = false;
    }
  });
})();

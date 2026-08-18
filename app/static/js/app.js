/* Shared helpers: CSRF aware fetch, toasts, tabs, clipboard. */
(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function request(url, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    opts.headers = Object.assign({ Accept: "application/json" }, opts.headers);
    if (!(opts.body instanceof FormData) && opts.body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      if (typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
    }
    if (["POST", "PATCH", "DELETE", "PUT"].includes((opts.method || "GET").toUpperCase())) {
      opts.headers["X-CSRFToken"] = csrfToken;
    }
    const response = await fetch(url, opts);
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    if (!response.ok) {
      const message = payload?.error || `Request failed (${response.status})`;
      const error = new Error(message);
      error.hint = payload?.hint;
      throw error;
    }
    return payload;
  }

  function toast(message, kind = "info", hint = null) {
    const host = document.getElementById("toast-host");
    if (!host) return;
    const element = document.createElement("div");
    element.className = `toast toast-${kind}`;
    element.textContent = message;
    if (hint) {
      const small = document.createElement("div");
      small.className = "hint mono";
      small.textContent = hint;
      element.appendChild(small);
    }
    host.appendChild(element);
    setTimeout(() => element.remove(), 7000);
  }

  function copyText(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => toast("Copied to clipboard", "success"),
        () => toast("Could not copy", "error")
      );
    }
  }

  function initTabs() {
    document.querySelectorAll("[data-tabs]").forEach((container) => {
      container.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
          container.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
          container.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
          tab.classList.add("active");
          container.querySelector(`[data-panel="${tab.dataset.tab}"]`)?.classList.add("active");
        });
      });
    });
  }

  function initCopyButtons() {
    document.querySelectorAll("#copy-command").forEach((button) => {
      button.addEventListener("click", () => {
        const explicit = button.dataset.command;
        const preview = document.getElementById("command-preview");
        copyText(explicit || preview?.textContent?.trim() || "");
      });
    });
  }

  function initHistorySearch() {
    const search = document.getElementById("history-search");
    if (!search) return;
    search.addEventListener("input", () => {
      const term = search.value.toLowerCase();
      document.querySelectorAll("#history-table tbody tr").forEach((row) => {
        row.hidden = term !== "" && !(row.dataset.target || "").includes(term);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initCopyButtons();
    initHistorySearch();
  });

  window.Toolkit = { request, toast, copyText };
})();

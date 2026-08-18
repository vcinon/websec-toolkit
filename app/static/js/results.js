/* Parsed result table: search, sort, filter, copy and open. */
(function () {
  "use strict";

  const panel = document.getElementById("results-panel");
  if (!panel) return;

  const scanId = panel.dataset.scanId;
  const tool = panel.dataset.tool;
  const table = document.getElementById("results-table");
  const tbody = table.querySelector("tbody");
  const countEl = document.getElementById("results-count");
  const search = document.getElementById("result-search");
  const statusFilter = document.getElementById("result-status-filter");
  const sizeFilter = document.getElementById("result-size-filter");
  const hostFilter = document.getElementById("result-host-filter");
  const extFilter = document.getElementById("result-ext-filter");
  const dedupe = document.getElementById("result-dedupe");

  let rows = [];
  let columns = [];
  let sortKey = null;
  let sortAsc = true;

  function filtered() {
    const term = (search?.value || "").toLowerCase();
    const statuses = (statusFilter?.value || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const minSize = parseInt(sizeFilter?.value || "", 10);
    const host = (hostFilter?.value || "").toLowerCase();
    const extension = (extFilter?.value || "").toLowerCase().replace(/^\./, "");
    const seen = new Set();

    let output = rows.filter((row) => {
      if (term && !JSON.stringify(row).toLowerCase().includes(term)) return false;
      if (statuses.length && !statuses.includes(String(row.status))) return false;
      if (!Number.isNaN(minSize) && (row.length || 0) < minSize) return false;
      if (host && !(row.host || "").toLowerCase().includes(host)) return false;
      if (extension && (row.extension || "").toLowerCase() !== extension) return false;
      if (dedupe?.checked) {
        if (seen.has(row.url)) return false;
        seen.add(row.url);
      }
      return true;
    });

    if (sortKey) {
      output = output.slice().sort((a, b) => {
        const left = a[sortKey] ?? "";
        const right = b[sortKey] ?? "";
        if (typeof left === "number" && typeof right === "number") return sortAsc ? left - right : right - left;
        return sortAsc
          ? String(left).localeCompare(String(right))
          : String(right).localeCompare(String(left));
      });
    }
    return output;
  }

  function render() {
    const visible = filtered();
    tbody.textContent = "";
    visible.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => {
        const td = document.createElement("td");
        const value = row[column];
        if (column === "url") {
          const link = document.createElement("a");
          link.href = value;
          link.target = "_blank";
          link.rel = "noreferrer noopener";
          link.textContent = value;
          td.className = "mono ellipsis";
          td.title = value;
          td.appendChild(link);
        } else if (column === "status" && value) {
          const span = document.createElement("span");
          span.className = "tag";
          span.textContent = value;
          td.appendChild(span);
        } else {
          td.textContent = value === null || value === undefined ? "" : String(value);
          if (column !== "source") td.className = "mono";
        }
        tr.appendChild(td);
      });
      const actions = document.createElement("td");
      const copy = document.createElement("button");
      copy.className = "btn btn-ghost btn-sm";
      copy.textContent = "Copy";
      copy.addEventListener("click", () => window.Toolkit.copyText(row.url));
      actions.appendChild(copy);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
    countEl.textContent = `${visible.length} of ${rows.length} results`;
  }

  table.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortAsc = sortKey === key ? !sortAsc : true;
      sortKey = key;
      render();
    });
  });

  [search, statusFilter, sizeFilter, hostFilter, extFilter, dedupe].forEach((input) =>
    input?.addEventListener("input", render)
  );

  window.Toolkit.request(`/api/scans/${scanId}/results`)
    .then((data) => {
      rows = data.results;
      columns = data.columns;
      render();
    })
    .catch((error) => window.Toolkit.toast(error.message, "error", error.hint));

  void tool;
})();

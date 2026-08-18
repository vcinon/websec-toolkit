/* Scan configuration form: presets, command preview and scan start. */
(function () {
  "use strict";

  const form = document.getElementById("scan-form");
  if (!form) return;

  const tool = form.dataset.tool;
  const previewEl = document.getElementById("command-preview");
  const previewError = document.getElementById("preview-error");
  const startButton = document.getElementById("start-scan");
  const categorySelect = document.getElementById("wordlist-category");
  const wordlistSelect = document.getElementById("wordlist-select");

  function collectConfig() {
    const config = {};
    for (const element of form.elements) {
      if (!element.name || element.name === "preset" || element.name === "scan_name") continue;
      if (element.type === "checkbox") config[element.name] = element.checked;
      else config[element.name] = element.value;
    }
    config.preset = form.querySelector('input[name="preset"]:checked')?.value || "custom";
    return config;
  }

  let previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 300);
  }

  async function updatePreview() {
    try {
      const data = await window.Toolkit.request("/api/scans/preview", {
        method: "POST",
        body: { tool, config: collectConfig() },
      });
      previewEl.textContent = data.command;
      previewError.textContent = "";
      startButton.dataset.ready = "true";
    } catch (error) {
      previewEl.textContent = "—";
      previewError.textContent = error.hint ? `${error.message} (${error.hint})` : error.message;
      startButton.dataset.ready = "false";
    }
  }

  form.addEventListener("input", schedulePreview);
  form.addEventListener("change", schedulePreview);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    startButton.disabled = true;
    try {
      const scan = await window.Toolkit.request("/api/scans", {
        method: "POST",
        body: {
          tool,
          name: form.elements.scan_name?.value || "",
          config: collectConfig(),
        },
      });
      window.Toolkit.toast(`Scan #${scan.id} started`, "success");
      window.ScanConsole.attach(scan.id, tool.toUpperCase());
      document.getElementById("console-card").scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    } finally {
      startButton.disabled = false;
    }
  });

  /* Wordlist category filtering (ffuf) */
  if (categorySelect && wordlistSelect) {
    const options = Array.from(wordlistSelect.options);
    categorySelect.addEventListener("change", () => {
      const category = categorySelect.value;
      wordlistSelect.innerHTML = "";
      options
        .filter((option) => !category || !option.dataset.category || option.dataset.category === category)
        .forEach((option) => wordlistSelect.appendChild(option));
      schedulePreview();
    });
    const preselected = wordlistSelect.dataset.selected;
    if (preselected) wordlistSelect.value = preselected;
  }

  /* Presets (ffuf) */
  const presetInputs = form.querySelectorAll('input[name="preset"]');
  if (presetInputs.length) {
    let presets = {};
    window.Toolkit.request(`/tools/${tool}/presets`)
      .then((data) => {
        presets = data;
        applyPreset(form.querySelector('input[name="preset"]:checked')?.value);
      })
      .catch(() => {});

    function applyPreset(key) {
      const preset = presets[key];
      if (!preset) return;
      Object.entries(preset.config).forEach(([field, value]) => {
        if (field === "category" && categorySelect) {
          categorySelect.value = value;
          categorySelect.dispatchEvent(new Event("change"));
          return;
        }
        if (field === "headers" && Array.isArray(value)) {
          const headers = form.elements.headers;
          if (headers) headers.value = value.map((h) => `${h.name}: ${h.value}`).join("\n");
          return;
        }
        const element = form.elements[field];
        if (!element) return;
        if (element.type === "checkbox") element.checked = Boolean(value);
        else element.value = value;
      });
      schedulePreview();
    }

    presetInputs.forEach((input) =>
      input.addEventListener("change", () => applyPreset(input.value))
    );
  }

  /* FUZZ placement helpers (ffuf) */
  document.querySelectorAll("[data-fuzz-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const url = form.elements.url;
      const headers = form.elements.headers;
      const target = button.dataset.fuzzTarget;
      if (target === "host" && headers) {
        const base = (url?.value || "").replace(/^https?:\/\//, "").split("/")[0] || "example.com";
        headers.value = `${headers.value ? headers.value.trim() + "\n" : ""}Host: FUZZ.${base}`;
      } else if (url) {
        let value = url.value.trim() || "https://example.local";
        value = value.replace(/\/?FUZZ/g, "").replace(/\?$/, "");
        url.value = target === "query" ? `${value}${value.includes("?") ? "&" : "?"}q=FUZZ` : `${value.replace(/\/$/, "")}/FUZZ`;
      }
      schedulePreview();
    });
  });

  schedulePreview();
})();

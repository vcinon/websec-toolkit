/* Wordlist library management (upload, rename, delete, default, preview). */
(function () {
  "use strict";

  const library = document.getElementById("wordlist-library");
  if (!library) return;

  const slug = library.dataset.slug;
  const previewEl = document.getElementById("wordlist-preview");
  const search = document.getElementById("wordlist-search");

  search?.addEventListener("input", () => {
    const term = search.value.toLowerCase();
    library.querySelectorAll("tbody tr").forEach((row) => {
      row.hidden = term !== "" && !(row.dataset.name || "").includes(term);
    });
  });

  library.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-wl-action]");
    if (!button) return;
    const row = button.closest("tr");
    const id = row.dataset.id;
    const action = button.dataset.wlAction;
    button.disabled = true;
    try {
      if (action === "preview") {
        const data = await window.Toolkit.request(`/api/wordlists/${slug}/${id}`);
        previewEl.hidden = false;
        previewEl.textContent = data.preview.join("\n") || "(empty)";
      } else if (action === "delete") {
        if (window.confirm(`Delete ${id}?`)) {
          await window.Toolkit.request(`/api/wordlists/${slug}/${id}`, { method: "DELETE" });
          row.remove();
          window.Toolkit.toast("Wordlist deleted", "success");
        }
      } else if (action === "rename") {
        const name = window.prompt("New file name", id.split("/")[1]);
        if (name) {
          await window.Toolkit.request(`/api/wordlists/${slug}/${id}`, {
            method: "PATCH",
            body: { name },
          });
          window.location.reload();
        }
      } else if (action === "default") {
        await window.Toolkit.request(`/api/wordlists/${slug}/default`, {
          method: "POST",
          body: { id },
        });
        window.Toolkit.toast(`${id} is now the default`, "success");
        window.location.reload();
      }
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("upload-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.target);
    try {
      const wordlist = await window.Toolkit.request(`/api/wordlists/${slug}`, {
        method: "POST",
        body: formData,
      });
      window.Toolkit.toast(`Uploaded ${wordlist.name}`, "success");
      window.location.reload();
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    }
  });

  document.getElementById("category-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = new FormData(event.target).get("name");
    try {
      await window.Toolkit.request(`/api/wordlists/${slug}/categories`, {
        method: "POST",
        body: { name },
      });
      window.location.reload();
    } catch (error) {
      window.Toolkit.toast(error.message, "error", error.hint);
    }
  });
})();

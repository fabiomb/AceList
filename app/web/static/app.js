// Small behaviors htmx does not cover. Loaded on every page.
"use strict";

(function () {
  const COPIED_FOR_MS = 1500;

  function fallbackCopy(text) {
    // For browsers without the async clipboard API.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
    }
    return fallbackCopy(text);
  }

  function announce(message) {
    const region = document.getElementById("announcer");
    if (region) region.textContent = message;
  }

  // Delegated, so buttons swapped in by htmx work too.
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    copy(button.dataset.copy).then(
      () => {
        button.classList.add("copied");
        button.title = "Copiado";
        announce("Hash copiado");
        setTimeout(() => {
          button.classList.remove("copied");
          button.title = "Copiar";
        }, COPIED_FOR_MS);
      },
      () => announce("No se pudo copiar")
    );
  });

  // Top bar search: "/" focuses it, arrows walk the matches, Escape or a click elsewhere closes them.
  function searchBox() {
    return document.getElementById("topbar-q");
  }

  function suggestions() {
    return document.getElementById("topbar-suggest");
  }

  function closeSuggestions() {
    const box = suggestions();
    if (box) box.innerHTML = "";
  }

  function isTyping(target) {
    return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
  }

  document.addEventListener("keydown", (event) => {
    const input = searchBox();
    if (!input) return;
    if (event.key === "/" && !isTyping(event.target) && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      input.focus();
      input.select();
      return;
    }
    const box = suggestions();
    if (!box || (!box.contains(event.target) && event.target !== input)) return;
    const items = Array.from(box.querySelectorAll(".suggest-item, .suggest-all"));
    const index = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      closeSuggestions();
      input.focus();
    } else if (event.key === "ArrowDown" && items.length) {
      event.preventDefault();
      items[Math.min(index + 1, items.length - 1)].focus();
    } else if (event.key === "ArrowUp" && index >= 0) {
      event.preventDefault();
      (index === 0 ? input : items[index - 1]).focus();
    }
  });

  document.addEventListener("click", (event) => {
    const form = event.target.closest(".topbar-search");
    if (!form) closeSuggestions();
  });

  // Check boxes of a form by name, also those outside it that point to it with `form`.
  function boxes(form, name) {
    return Array.from(form.elements).filter(
      (el) => el.type === "checkbox" && el.name === name && !el.disabled
    );
  }

  // "Choose all" boxes: data-check-all names the checkboxes of its form it toggles.
  document.addEventListener("change", (event) => {
    const master = event.target.closest("[data-check-all]");
    if (!master || !master.form) return;
    boxes(master.form, master.dataset.checkAll).forEach((box) => {
      box.checked = master.checked;
    });
    updateSelection(master.form);
  });

  // A selection bar (data-selection names its boxes): how many are chosen, and its
  // buttons enabled only when there is at least one.
  function updateSelection(form) {
    const name = form && form.dataset.selection;
    if (!name) return;
    const all = boxes(form, name);
    const chosen = all.filter((box) => box.checked).length;
    const count = form.querySelector("[data-selection-count]");
    if (count) {
      count.textContent =
        chosen === 0 ? "Ningún canal elegido"
        : chosen === 1 ? "1 canal elegido"
        : `${chosen} canales elegidos`;
    }
    form.querySelectorAll("[data-needs-selection]").forEach((button) => {
      button.disabled = chosen === 0;
    });
    Array.from(form.elements)
      .filter((el) => el.dataset && el.dataset.checkAll === name)
      .forEach((master) => {
        master.checked = all.length > 0 && chosen === all.length;
        master.indeterminate = chosen > 0 && chosen < all.length;
      });
  }

  document.addEventListener("change", (event) => {
    if (event.target.type === "checkbox" && !event.target.dataset.checkAll) {
      updateSelection(event.target.form);
    }
  });

  function initSelections(root) {
    // The browser may restore checked boxes when going back to the page.
    root.querySelectorAll("form[data-selection]").forEach(updateSelection);
  }
  document.addEventListener("DOMContentLoaded", () => initSelections(document));
  document.addEventListener("htmx:load", (event) => initSelections(event.target));

  // Buttons with data-confirm ask before submitting their form. Captured before htmx
  // sees the submit, so cancelling stops a boosted form too.
  document.addEventListener(
    "submit",
    (event) => {
      const button = event.submitter;
      if (button && button.dataset.confirm && !window.confirm(button.dataset.confirm)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true
  );

  // A new page (hx-boost) starts with the dropdown closed.
  document.addEventListener("htmx:beforeHistorySave", closeSuggestions);

  // A list file dropped anywhere on a page with a drop zone goes into its file field.
  let dragDepth = 0;

  function dropzone(event) {
    const types = event.dataTransfer ? Array.from(event.dataTransfer.types) : [];
    return types.includes("Files") ? document.querySelector("[data-dropzone]") : null;
  }

  document.addEventListener("dragenter", (event) => {
    const zone = dropzone(event);
    if (!zone) return;
    dragDepth += 1;
    const details = zone.closest("details");
    if (details) details.open = true;
    zone.classList.add("dragging");
  });

  document.addEventListener("dragover", (event) => {
    if (!dropzone(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });

  document.addEventListener("dragleave", (event) => {
    const zone = dropzone(event);
    if (!zone) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) zone.classList.remove("dragging");
  });

  document.addEventListener("drop", (event) => {
    const zone = dropzone(event);
    if (!zone) return;
    event.preventDefault();
    dragDepth = 0;
    zone.classList.remove("dragging");
    const file = event.dataTransfer.files[0];
    const input = zone.querySelector("input[type=file]");
    if (!file || !input) return;
    const chosen = new DataTransfer();
    chosen.items.add(file);
    input.files = chosen.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.form.querySelector("button[type=submit]").focus();
  });

  document.addEventListener("change", (event) => {
    const input = event.target;
    const zone = input.closest("[data-dropzone]");
    if (!zone || input.type !== "file") return;
    const label = zone.querySelector("[data-dropzone-label]");
    if (!label.dataset.empty) label.dataset.empty = label.innerHTML;
    const file = input.files[0];
    if (file) {
      label.textContent = `Archivo elegido: ${file.name}. Pulsa «Agregar».`;
    } else {
      label.innerHTML = label.dataset.empty;
    }
    const name = input.form.elements.namedItem("name");
    if (name) name.placeholder = file ? file.name.replace(/\.[^.]*$/, "") : "";
  });
})();

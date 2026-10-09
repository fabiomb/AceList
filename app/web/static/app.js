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

  // "Choose all" boxes: data-check-all names the checkboxes of its form it toggles.
  document.addEventListener("change", (event) => {
    const master = event.target.closest("[data-check-all]");
    if (!master || !master.form) return;
    const name = master.dataset.checkAll;
    master.form.querySelectorAll(`input[type=checkbox][name="${name}"]`).forEach((box) => {
      box.checked = master.checked;
    });
  });

  // A new page (hx-boost) starts with the dropdown closed.
  document.addEventListener("htmx:beforeHistorySave", closeSuggestions);
})();

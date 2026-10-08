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
})();

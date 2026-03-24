function bindEnhancedNavigation() {
  const shell = document.querySelector(".app-shell");
  if (!shell) {
    return;
  }

  const enhancedSelectors = [
    ".week-cell",
    ".week-nav a",
    ".tab-row a",
    ".booking-mode-tab",
    ".profile-link",
  ].join(", ");

  shell.querySelectorAll(enhancedSelectors).forEach((link) => {
    link.addEventListener("click", async (event) => {
      const href = link.getAttribute("href");
      if (!href || href.startsWith("http")) {
        return;
      }
      event.preventDefault();
      try {
        const response = await fetch(href, {
          headers: { "X-Requested-With": "parkassist" },
        });
        const html = await response.text();
        const nextDocument = new DOMParser().parseFromString(html, "text/html");
        const nextShell = nextDocument.querySelector(".app-shell");
        if (!nextShell) {
          window.location.href = href;
          return;
        }
        shell.innerHTML = nextShell.innerHTML;
        window.history.pushState({}, "", href);
        bindEnhancedNavigation();
      } catch (_error) {
        window.location.href = href;
      }
    });
  });
}

window.addEventListener("DOMContentLoaded", () => {
  document.body.classList.add("ready");
  bindEnhancedNavigation();
});

window.addEventListener("popstate", () => {
  window.location.reload();
});

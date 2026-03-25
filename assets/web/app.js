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
        bindVehicleSizeFilters();
      } catch (_error) {
        window.location.href = href;
      }
    });
  });
}

function bindVehicleSizeFilters() {
  document.querySelectorAll("[data-vehicle-size-form]").forEach((form) => {
    const sizeSelect = form.querySelector("[data-vehicle-size-select]");
    const spotSelect = form.querySelector("[data-spot-select]");
    const note = form.querySelector("[data-vehicle-fit-note]");
    if (!sizeSelect || !spotSelect) {
      return;
    }

    const sizeHeights = {
      "": null,
      small: 149,
      medium: 166,
      large: 176,
    };

    const updateOptions = () => {
      const selectedHeight = sizeHeights[sizeSelect.value] ?? null;
      const hiddenSpots = [];

      Array.from(spotSelect.options).forEach((option, index) => {
        if (index === 0) {
          option.hidden = false;
          option.disabled = false;
          return;
        }
        const maxHeight = option.dataset.maxHeight ? Number(option.dataset.maxHeight) : null;
        const hideOption = selectedHeight !== null && maxHeight !== null && selectedHeight > maxHeight;
        option.hidden = hideOption;
        option.disabled = hideOption;
        if (hideOption) {
          hiddenSpots.push(option.textContent.split("·")[0].trim());
        }
      });

      if (spotSelect.selectedOptions[0] && spotSelect.selectedOptions[0].hidden) {
        spotSelect.value = "";
      }

      if (!note) {
        return;
      }
      if (hiddenSpots.length) {
        note.hidden = false;
        note.textContent = `${hiddenSpots.join(" and ")} are hidden because they do not fit the selected vehicle height.`;
      } else {
        note.hidden = true;
        note.textContent = "";
      }
    };

    sizeSelect.addEventListener("change", updateOptions);
    updateOptions();
  });
}

window.addEventListener("DOMContentLoaded", () => {
  document.body.classList.add("ready");
  bindEnhancedNavigation();
  bindVehicleSizeFilters();
});

window.addEventListener("popstate", () => {
  window.location.reload();
});

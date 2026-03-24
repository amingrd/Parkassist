window.addEventListener("DOMContentLoaded", () => {
  document.body.classList.add("ready");
  document.querySelectorAll("[data-char-count]").forEach((input) => {
    const counterId = input.getAttribute("data-char-count");
    const counter = counterId ? document.getElementById(counterId) : null;
    if (!counter) {
      return;
    }
    const update = () => {
      counter.textContent = String(input.value.length);
    };
    input.addEventListener("input", update);
    update();
  });
});

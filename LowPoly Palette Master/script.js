const notes = [
  "ты невероятно красивая",
  "у тебя самый нежный взгляд",
  "мне с тобой спокойно и тепло",
  "ты мое любимое чудо дня",
  "я правда очень тобой дорожу"
];

const button = document.querySelector(".heart-button");
const toast = document.querySelector(".toast");
let noteIndex = 0;
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");

  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
  }, 2200);
}

function createHeart(x, y) {
  const heart = document.createElement("span");
  heart.className = "floating-heart";
  heart.textContent = "♡";
  heart.style.left = `${x}px`;
  heart.style.top = `${y}px`;
  document.body.appendChild(heart);
  heart.addEventListener("animationend", () => heart.remove(), { once: true });
}

button.addEventListener("click", event => {
  const message = notes[noteIndex % notes.length];
  noteIndex += 1;
  showToast(message);

  const rect = event.currentTarget.getBoundingClientRect();
  createHeart(rect.left + rect.width / 2, rect.top + 12);
});

const stateElement = document.getElementById("state");
const detailElement = document.getElementById("detail");
const indicator = document.getElementById("indicator");

const labels = {
  connected: "Local connector is ready",
  connecting: "Connecting to local executor…",
  offline: "Local connector is offline",
  error: "Local connector needs attention",
};

function render(status) {
  const state = labels[status?.state] ? status.state : "offline";
  stateElement.textContent = labels[state];
  detailElement.textContent = String(status?.detail || "").slice(0, 240);
  indicator.className = `indicator ${state}`;
}

function refresh() {
  chrome.runtime.sendMessage({ type: "get-status" }).then(render).catch(() => {
    render({ state: "offline", detail: "Extension service worker is restarting." });
  });
}

refresh();
setInterval(refresh, 3000);

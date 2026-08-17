const stateElement = document.getElementById("state");
const detailElement = document.getElementById("detail");
const indicator = document.getElementById("indicator");
const collaborationState = document.getElementById("collaboration-state");
const collaborationDetail = document.getElementById("collaboration-detail");
const collaborationIndicator = document.getElementById("collaboration-indicator");
const stopButton = document.getElementById("stop");

const labels = {
  connected: "Local connector is ready",
  connecting: "Connecting to local executor…",
  busy: "Bounded browser job is running",
  authorizing: "Mutation boundary is being authorized",
  offline: "Local connector is offline",
  error: "Local connector needs attention",
};

function render(status) {
  const connector = status?.connector || {};
  const state = labels[connector.state] ? connector.state : "offline";
  const active = status?.collaboration?.state === "active";
  stateElement.textContent = labels[state];
  detailElement.textContent = String(connector.detail || "").slice(0, 240);
  indicator.className = `indicator ${state}`;
  collaborationState.textContent = active ? "This tab is exposed" : "No tab is exposed";
  collaborationDetail.textContent = active
    ? "Targeted adapters may run bounded jobs only against this exact page."
    : "Open a page and click the extension to collaborate.";
  collaborationIndicator.className = `indicator ${active ? "connected" : "inactive"}`;
  stopButton.hidden = !active;
}

function refresh() {
  chrome.runtime.sendMessage({type: "get-status"}).then(render).catch(() => {
    render({
      connector: {state: "offline", detail: "Extension service worker is restarting."},
      collaboration: {state: "inactive"},
    });
  });
}

stopButton.addEventListener("click", () => {
  stopButton.disabled = true;
  chrome.runtime.sendMessage({type: "stop-collaboration"}).finally(() => {
    stopButton.disabled = false;
    refresh();
  });
});

refresh();
setInterval(refresh, 3000);

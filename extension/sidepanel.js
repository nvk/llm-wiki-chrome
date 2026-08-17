const stateElement = document.getElementById("state");
const detailElement = document.getElementById("detail");
const indicator = document.getElementById("indicator");
const collaborationState = document.getElementById("collaboration-state");
const collaborationDetail = document.getElementById("collaboration-detail");
const collaborationIndicator = document.getElementById("collaboration-indicator");
const workspaceElement = document.getElementById("workspace");
const collaborationList = document.getElementById("collaborations");
const stopAllButton = document.getElementById("stop-all");
const jobElement = document.getElementById("job");
const jobState = document.getElementById("job-state");
const jobProgress = document.getElementById("job-progress");
const jobDetail = document.getElementById("job-detail");
const cancelJobButton = document.getElementById("cancel-job");

const labels = {
  connected: "Local connector is ready",
  connecting: "Connecting to local executor…",
  busy: "Bounded browser job is running",
  authorizing: "Mutation boundary is being authorized",
  offline: "Local connector is offline",
  error: "Local connector needs attention",
};

function hostname(origin) {
  try {
    return new URL(origin).hostname;
  } catch (_error) {
    return "Shared HTTPS tab";
  }
}

function send(message) {
  return chrome.runtime.sendMessage(message).catch(() => ({stopped: false, cancelled: false}));
}

function collaborationRow(value) {
  const row = document.createElement("li");
  const label = document.createElement("div");
  const name = document.createElement("strong");
  const detail = document.createElement("span");
  const stop = document.createElement("button");
  name.textContent = hostname(value.origin);
  detail.textContent = value.selected ? "Most recently shared" : "Shared";
  label.className = "tab-label";
  label.append(name, detail);
  stop.className = "row-button";
  stop.type = "button";
  stop.textContent = "Stop";
  stop.addEventListener("click", () => {
    stop.disabled = true;
    send({type: "revoke-collaboration", collaboration_id: value.collaboration_id}).finally(refresh);
  });
  row.append(label, stop);
  return row;
}

function renderCollaborations(collaborations) {
  collaborationList.replaceChildren(...collaborations.map(collaborationRow));
  const count = collaborations.length;
  workspaceElement.hidden = count === 0;
  collaborationState.textContent = count === 0
    ? "No tabs are exposed"
    : `${count} explicitly shared ${count === 1 ? "tab" : "tabs"}`;
  collaborationDetail.textContent = count === 0
    ? "Open an HTTPS page and click the extension to collaborate."
    : "Targeted adapters can use only the grants listed below.";
  collaborationIndicator.className = `indicator ${count ? "connected" : "inactive"}`;
}

function renderJob(job) {
  const active = job && ["running", "authorizing", "cancelling"].includes(job.state);
  jobElement.hidden = !active;
  if (!active) return;
  const maximum = Number.isInteger(job.max_actions) && job.max_actions > 0 ? job.max_actions : 1;
  const count = Number.isInteger(job.action_count) ? Math.max(0, Math.min(job.action_count, maximum)) : 0;
  jobState.textContent = job.state === "authorizing"
    ? "Authorizing"
    : job.state === "cancelling" ? "Cancelling" : "Running";
  jobState.className = `pill ${job.state}`;
  jobProgress.max = maximum;
  jobProgress.value = count;
  jobDetail.textContent = `${count} of at most ${maximum} bounded actions` +
    (job.mutation_started ? " · mutation started" : "");
  cancelJobButton.disabled = job.state === "cancelling";
}

function render(status) {
  const connector = status?.connector || {};
  const state = labels[connector.state] ? connector.state : "offline";
  stateElement.textContent = labels[state];
  detailElement.textContent = String(connector.detail || "").slice(0, 240);
  indicator.className = `indicator ${state}`;
  renderCollaborations(Array.isArray(status?.collaborations) ? status.collaborations : []);
  renderJob(status?.job || null);
}

function refresh() {
  chrome.runtime.sendMessage({type: "get-status"}).then(render).catch(() => {
    render({
      connector: {state: "offline", detail: "Extension service worker is restarting."},
      collaborations: [],
      job: null,
    });
  });
}

stopAllButton.addEventListener("click", () => {
  stopAllButton.disabled = true;
  send({type: "stop-all-collaborations"}).finally(() => {
    stopAllButton.disabled = false;
    refresh();
  });
});

cancelJobButton.addEventListener("click", () => {
  cancelJobButton.disabled = true;
  send({type: "cancel-job"}).finally(refresh);
});

refresh();
setInterval(refresh, 2000);

import {
  BROWSER_PROTOCOL,
  validatePrivateValues,
  validateProgram,
} from "./protocol.mjs";
import {BrowserExecutor, ExecutionError} from "./executor.mjs";

const NATIVE_HOST = "net.llmwiki.browser_execution";
const CONNECTOR_STATE_KEY = "nativeConnectorState";
const COLLABORATION_STATE_KEY = "collaborationWorkspace";
const JOB_STATE_KEY = "activeJobState";
const MAX_COLLABORATIONS = 16;
const JOB_ID = /^[a-f0-9]{36}$/u;
const COLLABORATION_ID = /^[a-f0-9]{64}$/u;
const ERROR_CODE = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/u;

let nativePort = null;
let reconnectTimer = null;
let activeJob = null;
let workspaceSerial = Promise.resolve();

function hasExactKeys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && expected.slice().sort()
    .every((key, index) => key === actual[index]);
}

async function setConnectorState(state, detail = "") {
  await chrome.storage.session.set({
    [CONNECTOR_STATE_KEY]: {state, detail: String(detail || "").slice(0, 240)},
  });
}

async function setJobState(value) {
  await chrome.storage.session.set({[JOB_STATE_KEY]: value});
}

function collaborationId() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function validateCollaboration(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      !hasExactKeys(value, ["collaboration_id", "tab_id", "window_id", "url", "origin"]) ||
      !COLLABORATION_ID.test(value.collaboration_id) || !Number.isInteger(value.tab_id) ||
      !Number.isInteger(value.window_id) || typeof value.url !== "string" ||
      value.url.length > 16384 || typeof value.origin !== "string") return null;
  try {
    const url = new URL(value.url);
    if (url.protocol !== "https:" || url.username || url.password || url.origin !== value.origin) {
      return null;
    }
  } catch (_error) {
    return null;
  }
  return value;
}

function emptyWorkspace() {
  return {selected_collaboration_id: null, collaborations: []};
}

function validateWorkspace(value) {
  if (!hasExactKeys(value, ["selected_collaboration_id", "collaborations"]) ||
      !Array.isArray(value.collaborations) || value.collaborations.length > MAX_COLLABORATIONS) {
    return null;
  }
  const collaborations = value.collaborations.map(validateCollaboration);
  if (collaborations.some((item) => !item)) return null;
  const identifiers = new Set(collaborations.map((item) => item.collaboration_id));
  const tabs = new Set(collaborations.map((item) => item.tab_id));
  const urls = new Set(collaborations.map((item) => item.url));
  if (identifiers.size !== collaborations.length || tabs.size !== collaborations.length ||
      urls.size !== collaborations.length) return null;
  const selected = value.selected_collaboration_id;
  if (selected !== null && (!COLLABORATION_ID.test(selected) || !identifiers.has(selected))) return null;
  return {selected_collaboration_id: selected, collaborations};
}

function withWorkspaceMutation(operation) {
  const pending = workspaceSerial.then(operation, operation);
  workspaceSerial = pending.catch(() => {});
  return pending;
}

function targetFromTab(tab) {
  if (!Number.isInteger(tab?.id) || !Number.isInteger(tab?.windowId) ||
      typeof tab?.url !== "string" || tab.url.length > 16384) return null;
  try {
    const url = new URL(tab.url);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return {url: tab.url, origin: url.origin};
  } catch (_error) {
    return null;
  }
}

async function publishWorkspace(workspace) {
  if (!nativePort) return;
  sendThrough(nativePort, {
    type: "collaborations",
    selected_collaboration_id: workspace.selected_collaboration_id,
    collaborations: workspace.collaborations.map((value) => ({
      collaboration_id: value.collaboration_id,
      url: value.url,
      origin: value.origin,
    })),
  });
}

async function showCollaborationMarker(value) {
  if (!chrome.scripting?.executeScript || !Number.isInteger(value?.tab_id)) return;
  await chrome.scripting.executeScript({
    target: {tabId: value.tab_id},
    files: ["collaboration-marker.js"],
  }).catch(() => {});
}

async function clearCollaborationMarker(value) {
  if (!chrome.tabs?.sendMessage || !Number.isInteger(value?.tab_id)) return;
  await chrome.tabs.sendMessage(value.tab_id, {
    type: "llm-wiki-collaboration-revoke",
  }).catch(() => {});
}

async function persistWorkspace(workspace, removed = []) {
  await chrome.storage.session.set({[COLLABORATION_STATE_KEY]: workspace});
  for (const value of removed) {
    await clearCollaborationMarker(value);
    await chrome.action.setBadgeText({tabId: value.tab_id, text: ""}).catch(() => {});
    if (chrome.action?.setTitle) {
      await chrome.action.setTitle({
        tabId: value.tab_id,
        title: "LLM Wiki Browser Executor",
      }).catch(() => {});
    }
  }
  for (const value of workspace.collaborations) {
    await showCollaborationMarker(value);
    await chrome.action.setBadgeBackgroundColor({tabId: value.tab_id, color: "#317258"}).catch(() => {});
    await chrome.action.setBadgeText({tabId: value.tab_id, text: "ON"}).catch(() => {});
    if (chrome.action?.setTitle) {
      await chrome.action.setTitle({
        tabId: value.tab_id,
        title: "LLM Wiki agent controls this tab",
      }).catch(() => {});
    }
  }
  await publishWorkspace(workspace).catch(() => {});
}

async function checkedWorkspaceUnlocked() {
  const stored = await chrome.storage.session.get(COLLABORATION_STATE_KEY);
  const original = validateWorkspace(stored[COLLABORATION_STATE_KEY]);
  const workspace = original || emptyWorkspace();
  const collaborations = [];
  const removed = [];
  for (const value of workspace.collaborations) {
    try {
      const tab = await chrome.tabs.get(value.tab_id);
      const target = targetFromTab(tab);
      if (!target || tab.windowId !== value.window_id || target.origin !== value.origin) {
        removed.push(value);
        continue;
      }
      if (target.url === value.url) {
        collaborations.push(value);
      } else {
        collaborations.push({...value, collaboration_id: collaborationId(), url: target.url});
      }
    } catch (_error) {
      removed.push(value);
    }
  }
  const identifiers = new Set(collaborations.map((value) => value.collaboration_id));
  let selected = workspace.selected_collaboration_id;
  if (!identifiers.has(selected)) selected = collaborations.at(-1)?.collaboration_id || null;
  const checked = {selected_collaboration_id: selected, collaborations};
  if (!original || removed.length || JSON.stringify(checked) !== JSON.stringify(original)) {
    await persistWorkspace(checked, removed);
  }
  return checked;
}

function checkedWorkspace() {
  return withWorkspaceMutation(checkedWorkspaceUnlocked);
}

async function revokeCollaboration(collaborationId = null, revokeAll = false) {
  return withWorkspaceMutation(async () => {
    const workspace = await checkedWorkspaceUnlocked();
    const targetId = collaborationId || workspace.selected_collaboration_id;
    const removed = revokeAll
      ? workspace.collaborations
      : workspace.collaborations.filter((value) => value.collaboration_id === targetId);
    const removedIds = new Set(removed.map((value) => value.collaboration_id));
    const collaborations = workspace.collaborations.filter(
      (value) => !removedIds.has(value.collaboration_id),
    );
    const selected = removedIds.has(workspace.selected_collaboration_id)
      ? collaborations.at(-1)?.collaboration_id || null
      : workspace.selected_collaboration_id;
    const next = {selected_collaboration_id: selected, collaborations};
    await persistWorkspace(next, removed);
    return removed.length > 0;
  });
}

async function startCollaboration(tab) {
  const panel = Number.isInteger(tab?.id) ? chrome.sidePanel.open({tabId: tab.id}) : Promise.resolve();
  let exactTab = tab;
  if (Number.isInteger(tab?.id)) {
    exactTab = await chrome.tabs.get(tab.id).catch(() => tab);
  }
  const target = targetFromTab(exactTab);
  if (!target) {
    await panel.catch(() => {});
    return false;
  }
  await withWorkspaceMutation(async () => {
    const workspace = await checkedWorkspaceUnlocked();
    const existing = workspace.collaborations.find(
      (value) => value.tab_id === exactTab.id && value.url === target.url,
    );
    if (existing) {
      workspace.selected_collaboration_id = existing.collaboration_id;
      await persistWorkspace(workspace);
      return;
    }
    const removed = workspace.collaborations.filter(
      (value) => value.tab_id === exactTab.id || value.url === target.url,
    );
    let collaborations = workspace.collaborations.filter(
      (value) => value.tab_id !== exactTab.id && value.url !== target.url,
    );
    if (collaborations.length >= MAX_COLLABORATIONS) removed.push(collaborations.shift());
    const value = {
      collaboration_id: collaborationId(),
      tab_id: exactTab.id,
      window_id: exactTab.windowId,
      url: target.url,
      origin: target.origin,
    };
    collaborations.push(value);
    await persistWorkspace({
      selected_collaboration_id: value.collaboration_id,
      collaborations,
    }, removed.filter(Boolean));
  });
  await panel.catch(() => {});
  return true;
}

async function collaborationForProgram(program) {
  const workspace = await checkedWorkspace();
  const value = workspace.collaborations.find(
    (candidate) => candidate.collaboration_id === program.target.collaboration_id,
  );
  if (!value || value.collaboration_id !== program.target.collaboration_id ||
      value.url !== program.target.url || value.origin !== program.target.origin) return null;
  return value;
}

function sendThrough(port, value) {
  if (!port || nativePort !== port) throw new Error("native-port-unavailable");
  port.postMessage({protocol: BROWSER_PROTOCOL, ...value});
}

function finishBoundary(job, authorized) {
  const boundary = job?.boundary;
  if (!boundary || boundary.settled) return false;
  boundary.settled = true;
  clearTimeout(boundary.timer);
  job.boundary = null;
  boundary.resolve(authorized === true);
  return true;
}

function cancelActiveJob(port = null) {
  if (!activeJob || (port && activeJob.port !== port)) return false;
  activeJob.cancelled = true;
  finishBoundary(activeJob, false);
  setJobState({
    state: "cancelling",
    action_count: activeJob.executor?.actionCount || 0,
    max_actions: activeJob.executor?.program?.limits?.max_actions || 0,
    mutation_started: activeJob.executor?.mutationStarted === true,
  }).catch(() => {});
  return true;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNativeBridge();
  }, 1500);
}

function connectNativeBridge() {
  if (nativePort) return;
  try {
    const port = chrome.runtime.connectNative(NATIVE_HOST);
    nativePort = port;
    setConnectorState("connecting").catch(() => {});
    port.onMessage.addListener((message) => {
      handleNativeMessage(message, port).catch(() => {
        cancelActiveJob(port);
        setConnectorState("error", "Bounded executor rejected a local message.").catch(() => {});
      });
    });
    port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      cancelActiveJob(port);
      if (nativePort === port) nativePort = null;
      setConnectorState("offline", "Native host disconnected.").catch(() => {});
      scheduleReconnect();
    });
  } catch (_error) {
    nativePort = null;
    setConnectorState("offline", "Native host unavailable.").catch(() => {});
    scheduleReconnect();
  }
}

function filterFields(value, fields) {
  return Object.fromEntries(fields.filter((field) => Object.hasOwn(value, field))
    .map((field) => [field, value[field]]));
}

function safeErrorCode(error) {
  const code = error instanceof ExecutionError ? error.code : "internal-error";
  return ERROR_CODE.test(code) ? code : "internal-error";
}

function publicSnapshot(program, executor, status) {
  return filterFields({
    status,
    action_count: executor?.actionCount || 0,
    mutation_started: executor?.mutationStarted === true,
    private_result_count: status === "ok" ? Object.keys(executor?.privateResults || {}).length : 0,
  }, program.result.public_fields);
}

function requestMutation(job) {
  if (job.cancelled || job.boundary) return Promise.resolve(false);
  setConnectorState("authorizing", "The targeted adapter is authorizing one mutation boundary.")
    .catch(() => {});
  setJobState({
    state: "authorizing",
    action_count: job.executor?.actionCount || 0,
    max_actions: job.executor?.program?.limits?.max_actions || 0,
    mutation_started: false,
  }).catch(() => {});
  const remaining = Math.max(1, job.executor.deadline - Date.now());
  return new Promise((resolve) => {
    const boundary = {resolve, settled: false, timer: null};
    boundary.timer = setTimeout(() => finishBoundary(job, false), remaining);
    job.boundary = boundary;
    try {
      sendThrough(job.port, {type: "before-mutation", job_id: job.jobId});
    } catch (_error) {
      finishBoundary(job, false);
    }
  });
}

function handleMutationAuthorization(message, port) {
  const job = activeJob;
  if (!hasExactKeys(message, ["protocol", "type", "job_id", "authorized"]) ||
      !job || job.port !== port || job.jobId !== message.job_id ||
      typeof message.authorized !== "boolean" || !job.boundary) {
    cancelActiveJob(port);
    return;
  }
  setConnectorState("busy", "A bounded browser job is running.").catch(() => {});
  setJobState({
    state: "running",
    action_count: job.executor?.actionCount || 0,
    max_actions: job.executor?.program?.limits?.max_actions || 0,
    mutation_started: job.executor?.mutationStarted === true,
  }).catch(() => {});
  finishBoundary(job, message.authorized);
}

async function executeJob(message, port) {
  const jobId = message.job_id;
  if (activeJob) {
    sendThrough(port, {
      type: "result", job_id: jobId, status: "error", public: {}, private: {},
      error: "job-already-active",
    });
    return;
  }

  let program;
  try {
    if (!hasExactKeys(message, ["protocol", "type", "job_id", "program", "private_values"])) {
      throw new Error("invalid-job-shape");
    }
    program = await validateProgram(message.program);
    validatePrivateValues(program, message.private_values);
  } catch (_error) {
    sendThrough(port, {
      type: "result", job_id: jobId, status: "error", public: {}, private: {},
      error: "invalid-program",
    });
    return;
  }

  const collaboration = await collaborationForProgram(program);
  if (!collaboration) {
    sendThrough(port, {
      type: "result", job_id: jobId, status: "error", public: {}, private: {},
      error: "collaboration-required",
    });
    return;
  }

  let platformInfo;
  try {
    platformInfo = await chrome.runtime.getPlatformInfo();
  } catch (_error) {
    sendThrough(port, {
      type: "result", job_id: jobId, status: "error", public: {}, private: {},
      error: "executor-unavailable",
    });
    return;
  }
  const job = {
    jobId,
    port,
    boundary: null,
    cancelled: false,
    executor: null,
    collaborationId: collaboration.collaboration_id,
    tabId: collaboration.tab_id,
  };
  const executor = new BrowserExecutor({
    chromeApi: chrome,
    platform: platformInfo.os,
    isCancelled: () => job.cancelled,
    onProgress: ({actionCount, maxActions, mutationStarted}) => {
      setJobState({
        state: job.boundary ? "authorizing" : "running",
        action_count: actionCount,
        max_actions: maxActions,
        mutation_started: mutationStarted,
      }).catch(() => {});
    },
    targetTabId: collaboration.tab_id,
  });
  job.executor = executor;
  activeJob = job;
  await setConnectorState("busy", "A bounded browser job is running.").catch(() => {});
  await setJobState({
    state: "running",
    action_count: 0,
    max_actions: program.limits.max_actions,
    mutation_started: false,
  }).catch(() => {});

  try {
    const result = await executor.run(
      program,
      message.private_values,
      () => requestMutation(job),
    );
    if (job.cancelled) throw new ExecutionError("job-cancelled");
    sendThrough(port, {
      type: "result",
      job_id: jobId,
      status: "ok",
      public: filterFields(result.public, program.result.public_fields),
      private: filterFields(result.private, program.result.private_fields),
    });
  } catch (error) {
    try {
      sendThrough(port, {
        type: "result",
        job_id: jobId,
        status: "error",
        public: publicSnapshot(program, executor, "error"),
        private: {},
        error: safeErrorCode(error),
      });
    } catch (_sendError) {
      // A disconnected native port has already cancelled the job.
    }
  } finally {
    finishBoundary(job, false);
    if (activeJob === job) activeJob = null;
    await setJobState(null).catch(() => {});
    if (nativePort === port) {
      await setConnectorState("connected", "Ready for an exact-target job.").catch(() => {});
    }
  }
}

async function handleNativeMessage(message, port) {
  if (!message || message.protocol !== BROWSER_PROTOCOL) {
    cancelActiveJob(port);
    throw new Error("protocol-mismatch");
  }
  if (message.type === "ready") {
    if (!hasExactKeys(message, ["protocol", "type"])) {
      throw new Error("invalid-ready-message");
    }
    await setConnectorState("connected");
    await publishWorkspace(await checkedWorkspace()).catch(() => {});
    return;
  }
  if (message.type === "mutation-authorized") {
    handleMutationAuthorization(message, port);
    return;
  }
  if (message.type !== "job" || !JOB_ID.test(message.job_id || "")) {
    cancelActiveJob(port);
    throw new Error("unknown-native-message");
  }
  await executeJob(message, port);
}

async function configureExtension() {
  connectNativeBridge();
  await setJobState(null).catch(() => {});
  const workspace = await checkedWorkspace();
  await Promise.all(workspace.collaborations.map(showCollaborationMarker)).catch(() => {});
  await publishWorkspace(workspace).catch(() => {});
}

chrome.runtime.onInstalled.addListener(configureExtension);
chrome.runtime.onStartup.addListener(configureExtension);
configureExtension().catch(() => {});

chrome.action.onClicked.addListener((tab) => {
  startCollaboration(tab).catch(() => {
    setConnectorState("error", "Could not expose the selected HTTPS tab.").catch(() => {});
  });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (typeof changeInfo.url === "string" && activeJob?.tabId === tabId) cancelActiveJob();
  if (typeof changeInfo.url !== "string" && changeInfo.status !== "complete") return;
  checkedWorkspace().then((workspace) => {
    if (changeInfo.status !== "complete") return;
    const value = workspace.collaborations.find((candidate) => candidate.tab_id === tabId);
    if (value) showCollaborationMarker(value).catch(() => {});
  }).catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (activeJob?.tabId === tabId) cancelActiveJob();
  checkedWorkspace().catch(() => {});
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "connect-active-tab") {
    chrome.tabs.query({active: true, lastFocusedWindow: true}).then(async (tabs) => {
      if (tabs.length !== 1) return {connected: false};
      const connected = await startCollaboration(tabs[0]);
      if (!connected) return {connected: false};
      const workspace = await checkedWorkspace();
      return {
        connected: workspace.collaborations.some((value) => value.tab_id === tabs[0].id),
      };
    }).then(sendResponse).catch(() => sendResponse({connected: false}));
    return true;
  }
  if (message?.type === "stop-collaboration") {
    revokeCollaboration().then((stopped) => sendResponse({stopped})).catch(() => {
      sendResponse({stopped: false});
    });
    return true;
  }
  if (message?.type === "revoke-collaboration" && COLLABORATION_ID.test(message.collaboration_id || "")) {
    revokeCollaboration(message.collaboration_id).then((stopped) => sendResponse({stopped})).catch(() => {
      sendResponse({stopped: false});
    });
    return true;
  }
  if (message?.type === "stop-all-collaborations") {
    revokeCollaboration(null, true).then((stopped) => sendResponse({stopped})).catch(() => {
      sendResponse({stopped: false});
    });
    return true;
  }
  if (message?.type === "cancel-job") {
    sendResponse({cancelled: cancelActiveJob()});
    return false;
  }
  if (!message || message.type !== "get-status") return false;
  if (!nativePort) connectNativeBridge();
  Promise.all([
    chrome.storage.session.get(CONNECTOR_STATE_KEY),
    chrome.storage.session.get(JOB_STATE_KEY),
    checkedWorkspace(),
  ]).then(([stored, jobStored, workspace]) => {
    sendResponse({
      connector: stored[CONNECTOR_STATE_KEY] || {state: "offline", detail: "Connector starting."},
      collaborations: workspace.collaborations.map((value) => ({
        collaboration_id: value.collaboration_id,
        origin: value.origin,
        selected: value.collaboration_id === workspace.selected_collaboration_id,
      })),
      job: jobStored[JOB_STATE_KEY] || null,
    });
  });
  return true;
});

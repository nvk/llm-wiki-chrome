import {
  BROWSER_PROTOCOL,
  validatePrivateValues,
  validateProgram,
} from "./protocol.mjs";
import {BrowserExecutor, ExecutionError} from "./executor.mjs";

const NATIVE_HOST = "net.llmwiki.browser_execution";
const CONNECTOR_STATE_KEY = "nativeConnectorState";
const COLLABORATION_STATE_KEY = "activeCollaboration";
const JOB_ID = /^[a-f0-9]{36}$/u;
const COLLABORATION_ID = /^[a-f0-9]{64}$/u;
const ERROR_CODE = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/u;

let nativePort = null;
let reconnectTimer = null;
let activeJob = null;

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

async function publishCollaboration(value) {
  if (!nativePort) return;
  if (!value) {
    sendThrough(nativePort, {type: "collaboration", state: "inactive"});
    return;
  }
  sendThrough(nativePort, {
    type: "collaboration",
    state: "active",
    collaboration_id: value.collaboration_id,
    url: value.url,
    origin: value.origin,
  });
}

async function revokeCollaboration() {
  const stored = await chrome.storage.session.get(COLLABORATION_STATE_KEY);
  const prior = validateCollaboration(stored[COLLABORATION_STATE_KEY]);
  await chrome.storage.session.set({[COLLABORATION_STATE_KEY]: null});
  if (prior) await chrome.action.setBadgeText({tabId: prior.tab_id, text: ""}).catch(() => {});
  await publishCollaboration(null).catch(() => {});
}

async function currentCollaboration() {
  const stored = await chrome.storage.session.get(COLLABORATION_STATE_KEY);
  const value = validateCollaboration(stored[COLLABORATION_STATE_KEY]);
  if (!value) return null;
  try {
    const tab = await chrome.tabs.get(value.tab_id);
    if (tab.windowId !== value.window_id || tab.url !== value.url) {
      await revokeCollaboration();
      return null;
    }
  } catch (_error) {
    await revokeCollaboration();
    return null;
  }
  return value;
}

async function startCollaboration(tab) {
  const panel = Number.isInteger(tab?.id) ? chrome.sidePanel.open({tabId: tab.id}) : Promise.resolve();
  let url;
  try {
    url = new URL(tab?.url || "");
  } catch (_error) {
    await revokeCollaboration();
    await panel.catch(() => {});
    return;
  }
  if (!Number.isInteger(tab.id) || !Number.isInteger(tab.windowId) || url.protocol !== "https:" ||
      url.username || url.password || tab.url.length > 16384) {
    await revokeCollaboration();
    await panel.catch(() => {});
    return;
  }
  const prior = await currentCollaboration();
  if (prior && prior.tab_id !== tab.id) {
    await chrome.action.setBadgeText({tabId: prior.tab_id, text: ""}).catch(() => {});
  }
  const value = {
    collaboration_id: collaborationId(),
    tab_id: tab.id,
    window_id: tab.windowId,
    url: tab.url,
    origin: url.origin,
  };
  await chrome.storage.session.set({[COLLABORATION_STATE_KEY]: value});
  await chrome.action.setBadgeBackgroundColor({tabId: tab.id, color: "#317258"});
  await chrome.action.setBadgeText({tabId: tab.id, text: "ON"});
  await publishCollaboration(value).catch(() => {});
  await panel.catch(() => {});
}

async function collaborationForProgram(program) {
  const value = await currentCollaboration();
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

function cancelActiveJob(port) {
  if (!activeJob || activeJob.port !== port) return;
  activeJob.cancelled = true;
  finishBoundary(activeJob, false);
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
  };
  const executor = new BrowserExecutor({
    chromeApi: chrome,
    platform: platformInfo.os,
    isCancelled: () => job.cancelled,
    targetTabId: collaboration.tab_id,
  });
  job.executor = executor;
  activeJob = job;
  await setConnectorState("busy", "A bounded browser job is running.").catch(() => {});

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
    await publishCollaboration(await currentCollaboration()).catch(() => {});
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
  await publishCollaboration(await currentCollaboration()).catch(() => {});
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
  if (typeof changeInfo.url !== "string") return;
  currentCollaboration().then((value) => {
    if (value && value.tab_id === tabId && value.url !== changeInfo.url) {
      return revokeCollaboration();
    }
    return undefined;
  }).catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => {
  currentCollaboration().then((value) => {
    if (value && value.tab_id === tabId) return revokeCollaboration();
    return undefined;
  }).catch(() => {});
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "stop-collaboration") {
    revokeCollaboration().then(() => sendResponse({stopped: true})).catch(() => {
      sendResponse({stopped: false});
    });
    return true;
  }
  if (!message || message.type !== "get-status") return false;
  if (!nativePort) connectNativeBridge();
  Promise.all([
    chrome.storage.session.get(CONNECTOR_STATE_KEY),
    currentCollaboration(),
  ]).then(([stored, collaboration]) => {
    sendResponse({
      connector: stored[CONNECTOR_STATE_KEY] || {state: "offline", detail: "Connector starting."},
      collaboration: {state: collaboration ? "active" : "inactive"},
    });
  });
  return true;
});

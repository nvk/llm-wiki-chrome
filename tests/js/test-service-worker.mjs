import assert from "node:assert/strict";

import {canonicalProgramHash, validateProgram} from "../../extension/protocol.mjs";

const PROTOCOL = "llm-wiki-browser-executor/v1";
const JOB_ID = "a".repeat(36);

class EventHook {
  constructor() {
    this.listeners = [];
  }

  addListener(listener) {
    this.listeners.push(listener);
  }

  emit(...values) {
    for (const listener of this.listeners) listener(...values);
  }
}

class NativePort {
  constructor() {
    this.onMessage = new EventHook();
    this.onDisconnect = new EventHook();
    this.sent = [];
    this.waiters = [];
  }

  postMessage(message) {
    this.sent.push(structuredClone(message));
    for (const waiter of [...this.waiters]) waiter();
  }

  async next(predicate, start = 0) {
    const deadline = Date.now() + 2000;
    while (Date.now() < deadline) {
      const found = this.sent.slice(start).find(predicate);
      if (found) return found;
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 10);
        this.waiters.push(() => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
    throw new Error("Timed out waiting for a synthetic native message");
  }
}

const nativePort = new NativePort();
const stored = {};
const badges = new Map();
const tabs = new Map([
  [1, {
    id: 1,
    windowId: 1,
    url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
    active: true,
    status: "complete",
  }],
  [2, {
    id: 2,
    windowId: 1,
    url: "https://example.invalid/synthetic",
    active: false,
    status: "complete",
  }],
]);
let attached = false;

globalThis.chrome = {
  storage: {
    session: {
      set: async (value) => Object.assign(stored, value),
      get: async (key) => ({[key]: stored[key]}),
    },
  },
  action: {
    setBadgeText: async ({tabId, text}) => badges.set(tabId, text),
    setBadgeBackgroundColor: async () => {},
    onClicked: new EventHook(),
  },
  sidePanel: {open: async () => {}},
  runtime: {
    connectNative: () => nativePort,
    getPlatformInfo: async () => ({os: "mac"}),
    onInstalled: new EventHook(),
    onStartup: new EventHook(),
    onMessage: new EventHook(),
    lastError: null,
  },
  tabs: {
    onUpdated: new EventHook(),
    onRemoved: new EventHook(),
    create: async ({url, active}) => {
      const value = {id: 3, windowId: 1, url, active, status: "complete"};
      tabs.set(value.id, value);
      return structuredClone(value);
    },
    update: async (tabId, changes) => {
      const value = tabs.get(tabId);
      assert.ok(value);
      if (changes.active) {
        for (const candidate of tabs.values()) candidate.active = candidate.id === tabId;
      }
      Object.assign(value, changes);
      return structuredClone(value);
    },
    get: async (tabId) => {
      const value = tabs.get(tabId);
      if (!value) throw new Error("synthetic tab is closed");
      return structuredClone(value);
    },
  },
  windows: {
    update: async (windowId, changes) => {
      assert.equal(windowId, 1);
      assert.equal(changes.focused, true);
      return {id: 1, focused: true};
    },
    get: async (windowId) => {
      assert.equal(windowId, 1);
      return {id: 1, focused: true};
    },
  },
  debugger: {
    attach: async ({tabId}, version) => {
      assert.equal(tabId, 1);
      assert.equal(version, "1.3");
      attached = true;
    },
    detach: async ({tabId}) => {
      assert.equal(tabId, 1);
      attached = false;
    },
    sendCommand: async ({tabId}, method) => {
      assert.equal(tabId, 1);
      assert.equal(attached, true);
      assert.match(method, /^(?:DOM|Accessibility|Page)\.(?:enable|disable)$/u);
      return {};
    },
  },
};

async function waitFor(predicate) {
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("Timed out waiting for synthetic extension state");
}

async function runtimeMessage(message) {
  const listener = chrome.runtime.onMessage.listeners[0];
  return new Promise((resolve) => {
    const asynchronous = listener(message, {}, resolve);
    if (asynchronous === false) queueMicrotask(() => resolve(undefined));
  });
}

await import("../../extension/service-worker.js");
nativePort.onMessage.emit({protocol: PROTOCOL, type: "ready"});

chrome.action.onClicked.emit(structuredClone(tabs.get(1)));
await waitFor(() => stored.collaborationWorkspace?.collaborations?.length === 1);
assert.equal(stored.collaborationWorkspace.collaborations[0].url, tabs.get(1).url);
assert.match(stored.collaborationWorkspace.collaborations[0].collaboration_id, /^[a-f0-9]{64}$/u);
assert.equal(badges.get(1), "ON");
await nativePort.next((message) => message.type === "collaborations" && message.collaborations.length === 1);

tabs.get(1).active = false;
tabs.get(2).active = true;
chrome.action.onClicked.emit(structuredClone(tabs.get(2)));
await waitFor(() => stored.collaborationWorkspace?.collaborations?.length === 2);
assert.equal(badges.get(1), "ON");
assert.equal(badges.get(2), "ON");
const listMessage = await nativePort.next(
  (message) => message.type === "collaborations" && message.collaborations.length === 2,
);
assert.equal(listMessage.selected_collaboration_id, stored.collaborationWorkspace.selected_collaboration_id);

const status = await runtimeMessage({type: "get-status"});
assert.equal(status.collaborations.length, 2);
assert.equal(status.collaborations.filter((value) => value.selected).length, 1);
assert.ok(status.collaborations.every((value) => !Object.hasOwn(value, "url")));
assert.ok(status.collaborations.every((value) => !Object.hasOwn(value, "current")));

async function program(capability) {
  const actions = [
    {op: "open_or_focus_exact_url"},
    {op: "attach_debugger"},
    ...(capability === "mutation" ? [{op: "before_mutation"}] : []),
    {op: "detach_debugger"},
  ];
  const collaboration = stored.collaborationWorkspace.collaborations.find((value) => value.tab_id === 1);
  const value = {
    protocol: PROTOCOL,
    program_id: `synthetic-${capability}-v1`,
    program_sha256: "0".repeat(64),
    plan_sha256: "b".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability,
    target: {
      url: collaboration.url,
      origin: collaboration.origin,
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: collaboration.collaboration_id,
    },
    limits: {timeout_ms: 5000, max_actions: 10, max_repeat: 2},
    private_slots: [],
    actions,
    result: {public_fields: ["status"], private_fields: []},
  };
  value.program_sha256 = await canonicalProgramHash(value);
  return validateProgram(value);
}

const readProgram = await program("read");
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "job",
  job_id: JOB_ID,
  program: readProgram,
  private_values: {},
});
const readResult = await nativePort.next((message) => message.type === "result");
assert.equal(readResult.status, "ok");
assert.deepEqual(readResult.public, {status: "ok"});
assert.deepEqual(readResult.private, {});
assert.equal(attached, false);
await waitFor(() => stored.activeJobState === null);
await waitFor(() => stored.nativeConnectorState?.state === "connected");
assert.deepEqual(stored.nativeConnectorState, {
  state: "connected",
  detail: "Ready for an exact-target job.",
});

const mutationProgram = await program("mutation");
const mutationStart = nativePort.sent.length;
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "job",
  job_id: JOB_ID,
  program: mutationProgram,
  private_values: {},
});
await nativePort.next((message) => message.type === "before-mutation", mutationStart);
await waitFor(() => stored.activeJobState?.state === "authorizing");
assert.ok(stored.activeJobState.action_count >= 1);
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "mutation-authorized",
  job_id: JOB_ID,
  authorized: true,
});
const mutationResult = await nativePort.next((message) => message.type === "result", mutationStart);
assert.equal(mutationResult.status, "ok");
assert.deepEqual(mutationResult.public, {status: "ok"});
assert.equal(attached, false);
await waitFor(() => stored.activeJobState === null);

const cancelledStart = nativePort.sent.length;
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "job",
  job_id: JOB_ID,
  program: mutationProgram,
  private_values: {},
});
await nativePort.next((message) => message.type === "before-mutation", cancelledStart);
assert.equal((await runtimeMessage({type: "cancel-job"})).cancelled, true);
const cancelledResult = await nativePort.next(
  (message) => message.type === "result",
  cancelledStart,
);
assert.equal(cancelledResult.status, "error");
assert.equal(cancelledResult.error, "job-cancelled");
await waitFor(() => stored.activeJobState === null);

const invalidStart = nativePort.sent.length;
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "job",
  job_id: JOB_ID,
  program: readProgram,
  private_values: {},
  undeclared: "synthetic",
});
const invalidResult = await nativePort.next((message) => message.type === "result", invalidStart);
assert.equal(invalidResult.status, "error");
assert.equal(invalidResult.error, "invalid-program");
assert.deepEqual(invalidResult.public, {});

const wrongGrant = structuredClone(readProgram);
wrongGrant.target.collaboration_id = "f".repeat(64);
wrongGrant.program_sha256 = await canonicalProgramHash(wrongGrant);
const wrongGrantStart = nativePort.sent.length;
nativePort.onMessage.emit({
  protocol: PROTOCOL,
  type: "job",
  job_id: JOB_ID,
  program: wrongGrant,
  private_values: {},
});
const wrongGrantResult = await nativePort.next(
  (message) => message.type === "result",
  wrongGrantStart,
);
assert.equal(wrongGrantResult.error, "collaboration-required");

const second = stored.collaborationWorkspace.collaborations.find((value) => value.tab_id === 2);
assert.equal((await runtimeMessage({
  type: "revoke-collaboration",
  collaboration_id: second.collaboration_id,
})).stopped, true);
await waitFor(() => stored.collaborationWorkspace.collaborations.length === 1);
assert.equal(badges.get(2), "");

const prior = stored.collaborationWorkspace.collaborations[0];
tabs.get(1).url = `${tabs.get(1).url}/details`;
chrome.tabs.onUpdated.emit(1, {url: tabs.get(1).url});
const navigated = await waitFor(() => {
  const value = stored.collaborationWorkspace.collaborations[0];
  return value?.url === tabs.get(1).url && value;
});
assert.notEqual(navigated.collaboration_id, prior.collaboration_id);
assert.equal(navigated.origin, prior.origin);

tabs.get(1).url = "https://other.invalid/synthetic";
chrome.tabs.onUpdated.emit(1, {url: tabs.get(1).url});
await waitFor(() => stored.collaborationWorkspace.collaborations.length === 0);
assert.equal(badges.get(1), "");

process.stdout.write("ok\n");

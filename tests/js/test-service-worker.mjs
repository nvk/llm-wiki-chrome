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
let tab = {
  id: 1,
  windowId: 1,
  url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
  active: true,
  status: "complete",
};
let attached = false;

globalThis.chrome = {
  storage: {
    session: {
      set: async (value) => Object.assign(stored, value),
      get: async (key) => ({[key]: stored[key]}),
    },
  },
  action: {
    setBadgeText: async () => {},
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
    query: async (query) => {
      assert.deepEqual(query, {url: ["https://x.com/*"]});
      return tab ? [structuredClone(tab)] : [];
    },
    create: async ({url, active}) => {
      tab = {id: 1, windowId: 1, url, active, status: "complete"};
      return structuredClone(tab);
    },
    update: async (tabId, changes) => {
      assert.equal(tabId, tab.id);
      Object.assign(tab, changes);
      return structuredClone(tab);
    },
    get: async (tabId) => {
      assert.equal(tabId, tab.id);
      return structuredClone(tab);
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

await import("../../extension/service-worker.js");
nativePort.onMessage.emit({protocol: PROTOCOL, type: "ready"});
chrome.action.onClicked.emit(structuredClone(tab));
while (!stored.activeCollaboration) {
  await new Promise((resolve) => setTimeout(resolve, 0));
}
assert.equal(stored.activeCollaboration.url, tab.url);
assert.match(stored.activeCollaboration.collaboration_id, /^[a-f0-9]{64}$/u);
await nativePort.next((message) => message.type === "collaboration" && message.state === "active");

async function program(capability) {
  const actions = [
    {op: "open_or_focus_exact_url"},
    {op: "attach_debugger"},
    ...(capability === "mutation" ? [{op: "before_mutation"}] : []),
    {op: "detach_debugger"},
  ];
  const value = {
    protocol: PROTOCOL,
    program_id: `synthetic-${capability}-v1`,
    program_sha256: "0".repeat(64),
    plan_sha256: "b".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability,
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: stored.activeCollaboration.collaboration_id,
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
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(stored.nativeConnectorState, {
  state: "connected",
  detail: "Ready for an exact-target job.",
});

await new Promise((resolve) => setTimeout(resolve, 0));
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
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(stored.nativeConnectorState.state, "authorizing");
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
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(stored.nativeConnectorState.state, "connected");

await new Promise((resolve) => setTimeout(resolve, 0));
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

chrome.tabs.onUpdated.emit(tab.id, {url: `${tab.url}?drift=1`});
tab.url = `${tab.url}?drift=1`;
await new Promise((resolve) => setTimeout(resolve, 0));
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(stored.activeCollaboration, null);

process.stdout.write("ok\n");

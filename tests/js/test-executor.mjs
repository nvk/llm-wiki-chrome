import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import {BrowserExecutor, ExecutionError} from "../../extension/executor.mjs";
import {canonicalProgramHash, validateProgram} from "../../extension/protocol.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function property(name, value) {
  return {name, value: {value}};
}

function axNode({id, parentId, role, name, value, focused = false, backendDOMNodeId}) {
  return {
    nodeId: id,
    ...(parentId ? {parentId} : {}),
    role: {value: role},
    name: {value: name},
    ...(value === undefined ? {} : {value: {value}}),
    properties: [property("focused", focused)],
    ignored: false,
    ...(backendDOMNodeId === undefined ? {} : {backendDOMNodeId}),
  };
}

class FakeChrome {
  constructor(targetUrl, mode = "read") {
    this.targetUrl = targetUrl;
    this.mode = mode;
    this.nextTabId = 1;
    this.tab = null;
    this.window = {id: 1, focused: false};
    this.attached = false;
    this.focusedBackend = null;
    this.insertedText = "";
    this.commands = [];
    this.queries = [];
    this.clicks = 0;

    this.tabs = {
      query: async (query) => {
        this.queries.push(structuredClone(query));
        return this.tab ? [structuredClone(this.tab)] : [];
      },
      create: async ({url, active}) => {
        this.tab = {id: this.nextTabId++, windowId: 1, url, active, status: "complete"};
        return structuredClone(this.tab);
      },
      update: async (tabId, changes) => {
        assert.equal(tabId, this.tab.id);
        Object.assign(this.tab, changes);
        if (changes.url) this.tab.status = "complete";
        return structuredClone(this.tab);
      },
      get: async (tabId) => {
        assert.equal(tabId, this.tab.id);
        return structuredClone(this.tab);
      },
    };
    this.windows = {
      update: async (windowId, changes) => {
        assert.equal(windowId, this.window.id);
        Object.assign(this.window, changes);
        return structuredClone(this.window);
      },
      get: async (windowId) => {
        assert.equal(windowId, this.window.id);
        return structuredClone(this.window);
      },
    };
    this.debugger = {
      attach: async ({tabId}, version) => {
        assert.equal(tabId, this.tab.id);
        assert.equal(version, "1.3");
        this.attached = true;
      },
      detach: async ({tabId}) => {
        assert.equal(tabId, this.tab.id);
        this.attached = false;
      },
      sendCommand: async ({tabId}, method, parameters) => {
        assert.equal(tabId, this.tab.id);
        assert.equal(this.attached, true);
        this.commands.push({method, parameters: structuredClone(parameters)});
        return this.command(method, parameters);
      },
    };
  }

  tree() {
    if (this.mode === "mutation") {
      return [
        axNode({id: "root", role: "document", name: "Synthetic document"}),
        axNode({id: "dialog", parentId: "root", role: "dialog", name: "Synthetic editor"}),
        axNode({
          id: "textbox", parentId: "dialog", role: "textbox", name: "Synthetic field",
          value: this.insertedText, focused: this.focusedBackend === 11, backendDOMNodeId: 11,
        }),
        axNode({
          id: "replace", parentId: "dialog", role: "button", name: "Replace",
          backendDOMNodeId: 12,
        }),
      ];
    }
    return [
      axNode({id: "root", role: "main", name: "Synthetic space"}),
      axNode({id: "people", parentId: "root", role: "dialog", name: "People listeners"}),
      axNode({id: "one", parentId: "people", role: "listitem", name: "Synthetic attendee one"}),
      axNode({id: "two", parentId: "people", role: "link", name: "Synthetic attendee two"}),
      axNode({id: "meta", parentId: "root", role: "heading", name: "Synthetic space metadata"}),
    ];
  }

  command(method, parameters) {
    if (["DOM.enable", "DOM.disable", "Accessibility.enable", "Accessibility.disable",
      "Page.enable", "Page.disable", "DOM.scrollIntoViewIfNeeded"].includes(method)) return {};
    if (method === "Accessibility.getFullAXTree") return {nodes: this.tree()};
    if (method === "DOM.getDocument") return {root: {nodeId: 1}};
    if (method === "DOM.querySelector") {
      return {nodeId: parameters.selector.includes("synthetic-space-attendee-list") ? 42 : 0};
    }
    if (method === "DOM.getBoxModel") {
      return {model: {content: [0, 0, 20, 0, 20, 20, 0, 20]}};
    }
    if (method === "DOM.focus") {
      this.focusedBackend = parameters.backendNodeId;
      return {};
    }
    if (method === "Input.insertText") {
      this.insertedText = parameters.text;
      return {};
    }
    if (method === "Input.dispatchMouseEvent") {
      if (parameters.type === "mouseReleased") this.clicks += 1;
      return {};
    }
    if (method === "Input.dispatchKeyEvent") return {};
    if (method === "Page.captureScreenshot") {
      assert.equal(parameters.format, "jpeg");
      assert.equal(parameters.captureBeyondViewport, false);
      return {data: btoa("synthetic-jpeg-bytes")};
    }
    throw new Error(`Unexpected synthetic CDP method: ${method}`);
  }
}

function loadFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "tests", "fixtures", name), "utf8"));
}

async function mutationProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-mutation-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "a".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "mutation",
    target: {
      url: "https://docs.google.com/document/d/SYNTHETIC_DOCUMENT/edit",
      origin: "https://docs.google.com",
      path_prefixes: ["/document/d/SYNTHETIC_DOCUMENT/"],
    },
    limits: {timeout_ms: 5000, max_actions: 20, max_repeat: 2},
    private_slots: ["edit.value"],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "focus_ax",
        locator: {role: "textbox", within: {role: "dialog", name: "Synthetic editor"}},
      },
      {op: "insert_private_text", slot: "edit.value", replace_all: true},
      {op: "assert_ax_private_value", slot: "edit.value"},
      {op: "before_mutation"},
      {op: "click_ax", locator: {role: "button", name: "Replace"}},
      {op: "detach_debugger"},
    ],
    result: {public_fields: ["status", "action_count", "mutation_started"], private_fields: []},
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function screenshotProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-screenshot-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "c".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
    },
    limits: {timeout_ms: 5000, max_actions: 10, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "capture_viewport_private",
        private_result: "page.viewport",
        quality: 70,
        max_bytes: 16384,
      },
      {op: "detach_debugger"},
    ],
    result: {public_fields: ["status", "private_result_count"], private_fields: ["page.viewport"]},
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function testReadExecutionAndPrivateExtraction() {
  const program = await validateProgram(loadFixture("x-space-read-v1.json"));
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.deepEqual(Object.keys(result.private).sort(), ["space.attendees", "space.metadata"]);
  assert.equal(result.private["space.attendees"].length, 2);
  assert.equal(result.public.private_result_count, 2);
  assert.equal(fake.queries.length, 1);
  assert.deepEqual(fake.queries[0], {url: ["https://x.com/*"]});
  assert.equal(fake.commands.some(({method}) => method === "Runtime.evaluate"), false);
  assert.equal(fake.attached, false);
}

async function testMutationBoundaryAndPrivateInsertion() {
  const program = await mutationProgram();
  const fake = new FakeChrome(program.target.url, "mutation");
  let authorizations = 0;
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {"edit.value": "Synthetic replacement"}, async () => {
    authorizations += 1;
    return true;
  });
  assert.equal(authorizations, 1);
  assert.equal(result.public.mutation_started, true);
  assert.equal(fake.insertedText, "Synthetic replacement");
  assert.equal(fake.clicks, 1);
  assert.equal(fake.attached, false);
}

async function testPrivateViewportCapture() {
  const program = await screenshotProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.equal(result.public.private_result_count, 1);
  assert.deepEqual(result.private["page.viewport"], {
    mime_type: "image/jpeg",
    data_base64: btoa("synthetic-jpeg-bytes"),
  });
  assert.equal(fake.attached, false);
}

async function testMutationDenialFailsClosed() {
  const program = await mutationProgram();
  const fake = new FakeChrome(program.target.url, "mutation");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  await assert.rejects(
    executor.run(program, {"edit.value": "Synthetic replacement"}, async () => false),
    (error) => error instanceof ExecutionError && error.code === "mutation-denied",
  );
  assert.equal(fake.clicks, 0);
  assert.equal(fake.attached, false);
}

async function testTargetDriftIsNotRetried() {
  const program = await mutationProgram();
  const fake = new FakeChrome(program.target.url, "mutation");
  const original = fake.command.bind(fake);
  fake.command = (method, parameters) => {
    const result = original(method, parameters);
    if (method === "Page.enable") fake.tab.active = false;
    return result;
  };
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  await assert.rejects(
    executor.run(program, {"edit.value": "Synthetic replacement"}, async () => true),
    (error) => error instanceof ExecutionError && error.code === "target-focus-drift",
  );
  assert.equal(fake.clicks, 0);
  assert.equal(fake.attached, false);
}

async function testCancellationFailsClosed() {
  const program = await mutationProgram();
  const fake = new FakeChrome(program.target.url, "mutation");
  let checks = 0;
  const executor = new BrowserExecutor({
    chromeApi: fake,
    platform: "mac",
    isCancelled: () => ++checks > 3,
  });
  await assert.rejects(
    executor.run(program, {"edit.value": "Synthetic replacement"}, async () => true),
    (error) => error instanceof ExecutionError && error.code === "job-cancelled",
  );
  assert.equal(fake.clicks, 0);
  assert.equal(fake.attached, false);
}

await testReadExecutionAndPrivateExtraction();
await testMutationBoundaryAndPrivateInsertion();
await testPrivateViewportCapture();
await testMutationDenialFailsClosed();
await testTargetDriftIsNotRetried();
await testCancellationFailsClosed();
process.stdout.write("ok\n");

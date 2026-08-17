import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import {BrowserExecutor, ExecutionError} from "../../extension/executor.mjs";
import {canonicalProgramHash, validateProgram} from "../../extension/protocol.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

class EventHook {
  constructor() {
    this.listeners = [];
  }

  addListener(listener) {
    this.listeners.push(listener);
  }

  removeListener(listener) {
    this.listeners = this.listeners.filter((candidate) => candidate !== listener);
  }

  emit(...values) {
    for (const listener of [...this.listeners]) listener(...values);
  }
}

function property(name, value) {
  return {name, value: {value}};
}

function axNode({id, parentId, role, name, value, description, url, focused = false, backendDOMNodeId}) {
  return {
    nodeId: id,
    ...(parentId ? {parentId} : {}),
    role: {value: role},
    name: {value: name},
    ...(value === undefined ? {} : {value: {value}}),
    ...(description === undefined ? {} : {description: {value: description}}),
    properties: [
      property("focused", focused),
      ...(url === undefined ? [] : [property("url", url)]),
    ],
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
    this.scrolls = 0;

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
      onEvent: new EventHook(),
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
      axNode({
        id: "people", parentId: "root", role: "dialog", name: "People listeners",
        backendDOMNodeId: 21,
      }),
      axNode({id: "one", parentId: "people", role: "listitem", name: "Synthetic attendee one"}),
      axNode({
        id: "two", parentId: "people", role: "link", name: "Synthetic attendee two",
        description: "Synthetic profile link",
        url: "https://x.com/SYNTHETIC_ATTENDEE",
      }),
      ...(this.scrolls < 1 ? [] : [axNode({
        id: "three", parentId: "people", role: "link", name: "Synthetic attendee three",
        url: "https://x.com/SYNTHETIC_ATTENDEE_THREE",
      })]),
      axNode({id: "meta", parentId: "root", role: "heading", name: "Synthetic space metadata"}),
    ];
  }

  command(method, parameters) {
    if (["DOM.enable", "DOM.disable", "Accessibility.enable", "Accessibility.disable",
      "Page.enable", "Page.disable", "Log.disable", "Network.disable", "Runtime.disable",
      "DOM.scrollIntoViewIfNeeded"].includes(method)) return {};
    if (method === "Log.enable") {
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Log.entryAdded",
        {entry: {
          source: "javascript", level: "warning", text: "Synthetic browser diagnostic",
          timestamp: 1234, url: "https://x.com/i/spaces/SYNTHETIC_SPACE", lineNumber: 7,
        }},
      );
      return {};
    }
    if (method === "Runtime.enable") {
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Runtime.consoleAPICalled",
        {
          type: "error",
          args: [
            {type: "string", value: "Synthetic console diagnostic"},
            {type: "number", value: 7},
            {
              type: "object",
              subtype: "error",
              description: "not-retained object description",
              objectId: "not-retained-object-id",
              preview: {properties: [{name: "secret", value: "not-retained"}]},
            },
          ],
          executionContextId: 99,
          timestamp: 3000,
          stackTrace: {callFrames: [{url: "not-retained-stack"}]},
          context: "not-retained-context",
        },
      );
      return {};
    }
    if (method === "Network.enable") {
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Network.requestWillBeSent",
        {
          requestId: "synthetic-request-1",
          request: {
            url: "https://x.com/synthetic/api?private=discarded",
            method: "GET",
            headers: {authorization: "not-retained"},
            postData: "not-retained",
          },
          type: "Fetch",
          timestamp: 2000,
          initiator: {type: "script", stack: {callFrames: [{url: "not-retained"}]}},
        },
      );
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Network.responseReceived",
        {
          requestId: "synthetic-request-1",
          response: {
            status: 204,
            mimeType: "application/json",
            fromDiskCache: false,
            headers: {"set-cookie": "not-retained"},
          },
        },
      );
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Network.requestWillBeSent",
        {
          requestId: "synthetic-request-2",
          request: {url: "https://x.com/synthetic/failure", method: "POST"},
          type: "XHR",
          timestamp: 2001,
        },
      );
      this.debugger.onEvent.emit(
        {tabId: this.tab.id},
        "Network.loadingFailed",
        {
          requestId: "synthetic-request-2",
          errorText: "net::ERR_FAILED",
          canceled: true,
        },
      );
      return {};
    }
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
      if (parameters.type === "mouseWheel") this.scrolls += 1;
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
      collaboration_id: "d".repeat(64),
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
      collaboration_id: "d".repeat(64),
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

async function scrollAndLinkProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-scroll-link-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "d".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 5000, max_actions: 10, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {op: "scroll_viewport", direction: "down", distance_px: 640},
      {
        op: "extract_ax",
        locator: {role: "link", name: "Synthetic attendee two", unique: true},
        fields: ["name", "description", "url"],
        private_result: "page.link",
        max_items: 1,
      },
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.link"],
    },
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function scrollingCollectionProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-scrolling-collection-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "f".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 5000, max_actions: 8, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "collect_ax_by_scrolling",
        locator: {
          roles: ["listitem", "link"],
          within: {role: "dialog", name: "People listeners"},
        },
        fields: ["name", "url"],
        private_result: "page.people",
        max_items: 3,
        direction: "down",
        distance_px: 640,
        max_scrolls: 2,
        settle_ms: 50,
        dedupe_fields: ["name"],
        stable_rounds: 1,
        scroll_anchor: {role: "dialog", name: "People listeners", unique: true},
      },
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.people"],
    },
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function browserLogProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-browser-log-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "1".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 5000, max_actions: 8, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "start_log_capture",
        private_result: "page.browser_log",
        max_entries: 10,
        max_text_bytes: 1024,
      },
      {op: "assert_exact_target"},
      {op: "stop_log_capture"},
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.browser_log"],
    },
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function requestCaptureProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-request-capture-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "2".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 5000, max_actions: 8, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "start_request_capture",
        private_result: "page.requests",
        max_entries: 10,
        max_url_bytes: 1024,
      },
      {op: "assert_exact_target"},
      {op: "stop_request_capture"},
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.requests"],
    },
  };
  program.program_sha256 = await canonicalProgramHash(program);
  return validateProgram(program);
}

async function consoleCaptureProgram() {
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-console-capture-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "3".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      origin: "https://x.com",
      path_prefixes: ["/i/spaces/SYNTHETIC_SPACE"],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 5000, max_actions: 8, max_repeat: 2},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "start_console_capture",
        private_result: "page.console",
        max_entries: 10,
        max_arguments: 5,
        max_argument_bytes: 1024,
      },
      {op: "assert_exact_target"},
      {op: "stop_console_capture"},
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.console"],
    },
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

async function testViewportScrollAndPrivateLinkMetadata() {
  const program = await scrollAndLinkProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  const wheel = fake.commands.find(({method, parameters}) =>
    method === "Input.dispatchMouseEvent" && parameters.type === "mouseWheel");
  assert.equal(wheel.parameters.deltaY, 640);
  assert.deepEqual(result.private["page.link"], [{
    name: "Synthetic attendee two",
    description: "Synthetic profile link",
    url: "https://x.com/SYNTHETIC_ATTENDEE",
  }]);
  assert.equal(JSON.stringify(result.public).includes("SYNTHETIC_ATTENDEE"), false);
  assert.equal(fake.attached, false);
}

async function testScrollingCollectionDeduplicatesAndStopsAtBound() {
  const program = await scrollingCollectionProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.equal(fake.scrolls, 1);
  const wheel = fake.commands.find(({method, parameters}) =>
    method === "Input.dispatchMouseEvent" && parameters.type === "mouseWheel");
  assert.deepEqual({x: wheel.parameters.x, y: wheel.parameters.y}, {x: 10, y: 10});
  assert.deepEqual(result.private["page.people"], [
    {name: "Synthetic attendee one", url: null},
    {name: "Synthetic attendee two", url: "https://x.com/SYNTHETIC_ATTENDEE"},
    {name: "Synthetic attendee three", url: "https://x.com/SYNTHETIC_ATTENDEE_THREE"},
  ]);
  assert.equal(result.public.private_result_count, 1);
  assert.equal(fake.attached, false);
}

async function testPrivateBrowserLogCaptureIsBoundedAndCleanedUp() {
  const program = await browserLogProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.deepEqual(result.private["page.browser_log"], {
    entries: [{
      source: "javascript",
      level: "warning",
      text: "Synthetic browser diagnostic",
      timestamp: 1234,
      url: "https://x.com/i/spaces/SYNTHETIC_SPACE",
      line_number: 7,
    }],
    truncated: false,
  });
  assert.equal(fake.debugger.onEvent.listeners.length, 0);
  assert.equal(fake.attached, false);
}

async function testPrivateRequestCaptureDropsSensitivePayloadsAndCleansUp() {
  const program = await requestCaptureProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.deepEqual(result.private["page.requests"], {
    entries: [
      {
        method: "GET",
        url: "https://x.com/synthetic/api",
        resource_type: "Fetch",
        timestamp: 2000,
        status: 204,
        mime_type: "application/json",
        from_disk_cache: false,
        failed: false,
        error_text: null,
        canceled: false,
      },
      {
        method: "POST",
        url: "https://x.com/synthetic/failure",
        resource_type: "XHR",
        timestamp: 2001,
        status: null,
        mime_type: null,
        from_disk_cache: false,
        failed: true,
        error_text: "net::ERR_FAILED",
        canceled: true,
      },
    ],
    truncated: false,
  });
  assert.equal(JSON.stringify(result.private).includes("not-retained"), false);
  assert.equal(JSON.stringify(result.private).includes("private=discarded"), false);
  assert.equal(fake.debugger.onEvent.listeners.length, 0);
  assert.equal(fake.attached, false);
}

async function testInvalidPrivateRequestFailsClosedAndCleansUp() {
  const program = await requestCaptureProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const original = fake.command.bind(fake);
  fake.command = (method, parameters) => {
    if (method === "Network.enable") {
      fake.debugger.onEvent.emit(
        {tabId: fake.tab.id},
        "Network.requestWillBeSent",
        {requestId: "synthetic-invalid", request: {url: "not a URL", method: "GET"}, type: "Fetch"},
      );
      return {};
    }
    return original(method, parameters);
  };
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  await assert.rejects(
    executor.run(program, {}, async () => false),
    (error) => error instanceof ExecutionError && error.code === "private-request-invalid",
  );
  assert.equal(fake.debugger.onEvent.listeners.length, 0);
  assert.equal(fake.attached, false);
}

async function testPrivateConsoleCaptureKeepsOnlyBoundedScalarsAndCleansUp() {
  const program = await consoleCaptureProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  const result = await executor.run(program, {}, async () => false);
  assert.deepEqual(result.private["page.console"], {
    entries: [{
      type: "error",
      timestamp: 3000,
      arguments: [
        {type: "string", subtype: null, value: "Synthetic console diagnostic"},
        {type: "number", subtype: null, value: 7},
        {type: "object", subtype: "error", value: null},
      ],
      arguments_truncated: false,
    }],
    truncated: false,
  });
  for (const excluded of [
    "not-retained object description", "not-retained-object-id", "not-retained-stack",
    "not-retained-context", "secret",
  ]) {
    assert.equal(JSON.stringify(result.private).includes(excluded), false);
  }
  assert.equal(fake.debugger.onEvent.listeners.length, 0);
  assert.equal(fake.attached, false);
}

async function testInvalidPrivateConsoleEventFailsClosedAndCleansUp() {
  const program = await consoleCaptureProgram();
  const fake = new FakeChrome(program.target.url, "read");
  const original = fake.command.bind(fake);
  fake.command = (method, parameters) => {
    if (method === "Runtime.enable") {
      fake.debugger.onEvent.emit(
        {tabId: fake.tab.id},
        "Runtime.consoleAPICalled",
        {type: "unsupported", args: [], timestamp: 1},
      );
      return {};
    }
    return original(method, parameters);
  };
  const executor = new BrowserExecutor({chromeApi: fake, platform: "mac"});
  await assert.rejects(
    executor.run(program, {}, async () => false),
    (error) => error instanceof ExecutionError && error.code === "private-console-invalid",
  );
  assert.equal(fake.debugger.onEvent.listeners.length, 0);
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
await testViewportScrollAndPrivateLinkMetadata();
await testScrollingCollectionDeduplicatesAndStopsAtBound();
await testPrivateBrowserLogCaptureIsBoundedAndCleanedUp();
await testPrivateRequestCaptureDropsSensitivePayloadsAndCleansUp();
await testInvalidPrivateRequestFailsClosedAndCleansUp();
await testPrivateConsoleCaptureKeepsOnlyBoundedScalarsAndCleansUp();
await testInvalidPrivateConsoleEventFailsClosedAndCleansUp();
await testMutationDenialFailsClosed();
await testTargetDriftIsNotRetried();
await testCancellationFailsClosed();
process.stdout.write("ok\n");

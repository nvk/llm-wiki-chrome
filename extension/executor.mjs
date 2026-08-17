const CDP_VERSION = "1.3";
const MAX_EXTRACTED_FIELD_BYTES = 16_384;
const MAX_PRIVATE_RESULTS_BYTES = 524_288;
const ALLOWED_CDP_METHODS = new Set([
  "Accessibility.disable", "Accessibility.enable", "Accessibility.getFullAXTree",
  "DOM.disable", "DOM.enable", "DOM.focus", "DOM.getBoxModel", "DOM.getDocument",
  "DOM.querySelector", "DOM.scrollIntoViewIfNeeded", "Input.dispatchKeyEvent",
  "Input.dispatchMouseEvent", "Input.insertText", "Page.disable", "Page.enable",
  "Page.captureScreenshot", "Log.disable", "Log.enable",
  "Network.disable", "Network.enable",
  "Runtime.disable", "Runtime.enable",
]);
const CONSOLE_TYPES = new Set([
  "log", "debug", "info", "error", "warning", "dir", "dirxml", "table", "trace",
  "clear", "startGroup", "startGroupCollapsed", "endGroup", "assert", "profile",
  "profileEnd", "count", "timeEnd",
]);
const REMOTE_OBJECT_TYPES = new Set([
  "object", "function", "undefined", "string", "number", "boolean", "symbol", "bigint",
]);
const RETRYABLE_WAIT_CODES = new Set([
  "element-not-found", "element-state-mismatch", "element-ambiguous", "target-not-ready",
]);
const RECOVERABLE_BRANCH_CODES = new Set([
  "element-not-found", "element-state-mismatch", "element-ambiguous",
  "element-not-visible", "element-has-no-dom-node", "element-scroll-failed",
]);

export class ExecutionError extends Error {
  constructor(code) {
    super(code);
    this.name = "ExecutionError";
    this.code = code;
  }
}

function fail(code) {
  throw new ExecutionError(code);
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function axValue(node, key) {
  if (["name", "role", "value", "description"].includes(key)) return node[key]?.value;
  return node.properties?.find((property) => property.name === key)?.value?.value;
}

function normalized(value) {
  return String(value ?? "").toLocaleLowerCase("en-US");
}

function boxCenter(box) {
  const quad = box?.content || box?.border;
  if (!Array.isArray(quad) || quad.length !== 8) fail("element-not-visible");
  return {
    x: (quad[0] + quad[2] + quad[4] + quad[6]) / 4,
    y: (quad[1] + quad[3] + quad[5] + quad[7]) / 4,
  };
}

function keyDefinition(name, platform) {
  const primary = platform === "mac" ? "meta" : "control";
  const resolved = name === "platform-primary" ? primary : name;
  const named = {
    control: {key: "Control", code: "ControlLeft", modifier: 2, vk: 17},
    meta: {key: "Meta", code: "MetaLeft", modifier: 4, vk: 91},
    alt: {key: "Alt", code: "AltLeft", modifier: 1, vk: 18},
    shift: {key: "Shift", code: "ShiftLeft", modifier: 8, vk: 16},
    enter: {key: "Enter", code: "Enter", vk: 13},
    escape: {key: "Escape", code: "Escape", vk: 27},
    tab: {key: "Tab", code: "Tab", vk: 9},
    "arrow-up": {key: "ArrowUp", code: "ArrowUp", vk: 38},
    "arrow-down": {key: "ArrowDown", code: "ArrowDown", vk: 40},
    "arrow-left": {key: "ArrowLeft", code: "ArrowLeft", vk: 37},
    "arrow-right": {key: "ArrowRight", code: "ArrowRight", vk: 39},
    backspace: {key: "Backspace", code: "Backspace", vk: 8},
    delete: {key: "Delete", code: "Delete", vk: 46},
  };
  if (named[resolved]) return named[resolved];
  if (/^[a-z]$/.test(resolved)) {
    return {key: resolved, code: `Key${resolved.toUpperCase()}`, vk: resolved.toUpperCase().charCodeAt(0)};
  }
  if (/^[0-9]$/.test(resolved)) {
    return {key: resolved, code: `Digit${resolved}`, vk: resolved.charCodeAt(0)};
  }
  fail("invalid-key-chord");
}

export class BrowserExecutor {
  constructor({
    chromeApi,
    platform = "unknown",
    isCancelled = () => false,
    onProgress = () => {},
    targetTabId,
  }) {
    this.chrome = chromeApi;
    this.platform = platform;
    this.isCancelled = isCancelled;
    this.onProgress = onProgress;
    this.program = null;
    this.privateValues = {};
    this.privateResults = {};
    this.tabId = null;
    this.targetTabId = Number.isInteger(targetTabId) ? targetTabId : null;
    this.expectedUrl = null;
    this.attached = false;
    this.actionCount = 0;
    this.mutationStarted = false;
    this.logCapture = null;
    this.requestCapture = null;
    this.consoleCapture = null;
    this.deadline = 0;
  }

  async run(program, privateValues, requestMutation) {
    this.program = program;
    this.privateValues = privateValues;
    this.requestMutation = requestMutation;
    this.expectedUrl = program.target.url;
    this.deadline = Date.now() + program.limits.timeout_ms;
    try {
      await this.runActions(program.actions);
      if (this.attached) fail("debugger-left-attached");
      return {
        public: {
          status: "ok",
          action_count: this.actionCount,
          mutation_started: this.mutationStarted,
          private_result_count: Object.keys(this.privateResults).length,
        },
        private: this.privateResults,
      };
    } finally {
      if (this.consoleCapture) await this.stopConsoleCapture(true);
      if (this.requestCapture) await this.stopRequestCapture(true);
      if (this.logCapture) await this.stopLogCapture(true);
      if (this.attached) await this.detachDebugger(true);
    }
  }

  checkDeadline() {
    if (this.isCancelled()) fail("job-cancelled");
    if (Date.now() >= this.deadline) fail("job-timeout");
  }

  async runActions(actions) {
    for (const action of actions) {
      this.checkDeadline();
      this.actionCount += 1;
      if (this.actionCount > this.program.limits.max_actions) fail("action-limit-exceeded");
      this.onProgress({
        actionCount: this.actionCount,
        maxActions: this.program.limits.max_actions,
        mutationStarted: this.mutationStarted,
      });
      if (this.tabId !== null && action.op !== "open_or_focus_exact_url") {
        await this.assertExactTarget();
      }
      await this.runAction(action);
    }
  }

  async runAction(action) {
    const handlers = {
      open_or_focus_exact_url: () => this.openOrFocus(),
      navigate_same_origin: () => this.navigate(action.url),
      assert_exact_target: () => this.assertExactTarget(),
      attach_debugger: () => this.attachDebugger(),
      detach_debugger: () => this.detachDebugger(false),
      wait_ax: () => this.waitFor(() => this.findAX(action.locator, false), action.timeout_ms),
      wait_dom: () => this.waitFor(() => this.findDOM(action.locator), action.timeout_ms),
      assert_ax: () => this.findAX(action.locator, false),
      first_success: () => this.firstSuccess(action.branches),
      click_ax: () => this.clickAX(action.locator),
      click_dom: () => this.clickDOM(action.locator),
      focus_ax: () => this.focusAX(action.locator),
      dispatch_key_chord: () => this.dispatchKeyChord(action.keys),
      insert_private_text: () => this.insertPrivateText(action.slot, action.replace_all),
      assert_ax_private_value: () => this.assertFocusedPrivateValue(action.slot),
      assert_ax_private_sha256: () => this.assertAXPrivateSHA256(action),
      extract_ax: () => this.extractAX(action),
      extract_ax_collection: () => this.extractAX(action),
      collect_ax_by_scrolling: () => this.collectAXByScrolling(action),
      capture_viewport_private: () => this.captureViewport(action),
      scroll_viewport: () => this.scrollViewport(action),
      start_log_capture: () => this.startLogCapture(action),
      stop_log_capture: () => this.stopLogCapture(false),
      start_request_capture: () => this.startRequestCapture(action),
      stop_request_capture: () => this.stopRequestCapture(false),
      start_console_capture: () => this.startConsoleCapture(action),
      stop_console_capture: () => this.stopConsoleCapture(false),
      before_mutation: () => this.beforeMutation(),
    };
    const handler = handlers[action.op];
    if (!handler) fail("unsupported-action");
    await handler();
  }

  async openOrFocus() {
    if (this.tabId !== null) fail("target-already-opened");
    if (this.targetTabId === null) fail("collaboration-target-missing");
    let tab;
    try {
      tab = await this.chrome.tabs.get(this.targetTabId);
      if (tab.url !== this.expectedUrl && tab.pendingUrl !== this.expectedUrl) {
        fail("collaboration-target-drift");
      }
      this.tabId = this.targetTabId;
      await this.chrome.windows.update(tab.windowId, {focused: true});
      await this.chrome.tabs.update(this.tabId, {active: true});
      await this.waitForTab(this.expectedUrl);
    } catch (error) {
      if (error instanceof ExecutionError) throw error;
      fail("collaboration-target-lost");
    }
    await this.assertExactTarget();
  }

  async waitForTab(expectedUrl) {
    await this.waitFor(async () => {
      let tab;
      try {
        tab = await this.chrome.tabs.get(this.tabId);
      } catch (_error) {
        fail("target-tab-lost");
      }
      if (tab.url !== expectedUrl || tab.status !== "complete") fail("target-not-ready");
      return tab;
    }, Math.min(30000, this.program.limits.timeout_ms));
  }

  async assertExactTarget() {
    if (!Number.isInteger(this.tabId)) fail("target-tab-missing");
    let tab;
    let window;
    try {
      tab = await this.chrome.tabs.get(this.tabId);
      window = await this.chrome.windows.get(tab.windowId);
    } catch (_error) {
      fail("target-tab-lost");
    }
    if (tab.url !== this.expectedUrl || !tab.active || !window.focused) fail("target-focus-drift");
    return tab;
  }

  async navigate(url) {
    if (!this.attached) fail("debugger-not-attached");
    const prior = this.expectedUrl;
    this.expectedUrl = url;
    try {
      await this.chrome.tabs.update(this.tabId, {url});
      await this.waitForTab(url);
    } catch (error) {
      this.expectedUrl = prior;
      if (error instanceof ExecutionError) throw error;
      fail("navigation-failed");
    }
  }

  async attachDebugger() {
    if (this.attached || !Number.isInteger(this.tabId)) fail("debugger-state-invalid");
    try {
      await this.chrome.debugger.attach({tabId: this.tabId}, CDP_VERSION);
      this.attached = true;
      await this.command("DOM.enable", {});
      await this.command("Accessibility.enable", {});
      await this.command("Page.enable", {});
    } catch (error) {
      if (this.attached) await this.detachDebugger(true);
      if (error instanceof ExecutionError) throw error;
      fail("debugger-attach-failed");
    }
  }

  async detachDebugger(bestEffort) {
    if (!this.attached) {
      if (bestEffort) return;
      fail("debugger-not-attached");
    }
    for (const method of ["Accessibility.disable", "DOM.disable", "Page.disable"]) {
      try {
        await this.command(method, {});
      } catch (_error) {
        if (!bestEffort) fail("debugger-disable-failed");
      }
    }
    try {
      await this.chrome.debugger.detach({tabId: this.tabId});
    } catch (_error) {
      if (!bestEffort) fail("debugger-detach-failed");
    } finally {
      this.attached = false;
    }
  }

  async command(method, parameters) {
    if (!this.attached || !ALLOWED_CDP_METHODS.has(method)) fail("cdp-method-blocked");
    try {
      return await this.chrome.debugger.sendCommand({tabId: this.tabId}, method, parameters);
    } catch (_error) {
      fail("cdp-command-failed");
    }
  }

  async waitFor(operation, timeoutMs) {
    const stop = Math.min(this.deadline, Date.now() + timeoutMs);
    const attempts = this.program.limits.max_repeat;
    const delay = attempts > 1 ? Math.max(20, Math.floor(timeoutMs / (attempts - 1))) : timeoutMs;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      this.checkDeadline();
      try {
        return await operation();
      } catch (error) {
        if (!(error instanceof ExecutionError)) throw error;
        if (!RETRYABLE_WAIT_CODES.has(error.code)) throw error;
        if (attempt + 1 >= attempts || Date.now() + delay > stop) throw error;
        await sleep(delay);
        await this.assertExactTarget();
      }
    }
    fail("wait-exhausted");
  }

  async firstSuccess(branches) {
    for (const branch of branches) {
      try {
        await this.runActions(branch);
        return;
      } catch (error) {
        if (!(error instanceof ExecutionError)) throw error;
        if (!RECOVERABLE_BRANCH_CODES.has(error.code)) throw error;
        await this.assertExactTarget();
      }
    }
    fail("all-branches-failed");
  }

  async findDOM(locator) {
    if (!this.attached || typeof locator.selector !== "string") fail("dom-locator-invalid");
    const document = await this.command("DOM.getDocument", {depth: 0, pierce: false});
    const result = await this.command("DOM.querySelector", {
      nodeId: document.root.nodeId,
      selector: locator.selector,
    });
    if (!result.nodeId) fail("element-not-found");
    let box = null;
    try {
      box = await this.command("DOM.getBoxModel", {nodeId: result.nodeId});
    } catch (_error) {
      box = null;
    }
    const visible = Boolean(box?.model);
    if (locator.visible !== undefined && locator.visible !== visible) fail("element-state-mismatch");
    return {nodeId: result.nodeId, box: box?.model || null};
  }

  async axTree() {
    if (!this.attached) fail("debugger-not-attached");
    const result = await this.command("Accessibility.getFullAXTree", {});
    const nodes = Array.isArray(result.nodes) ? result.nodes.filter((node) => !node.ignored) : [];
    return {nodes, byId: new Map(nodes.map((node) => [node.nodeId, node]))};
  }

  nodeMatches(node, locator) {
    const role = String(axValue(node, "role") ?? "");
    const name = String(axValue(node, "name") ?? "");
    if (locator.role !== undefined && role !== locator.role) return false;
    if (locator.roles !== undefined && !locator.roles.includes(role)) return false;
    if (locator.name !== undefined && name !== locator.name) return false;
    if (locator.name_contains !== undefined && !normalized(name).includes(normalized(locator.name_contains))) return false;
    if (locator.name_contains_any !== undefined &&
        !locator.name_contains_any.some((value) => normalized(name).includes(normalized(value)))) return false;
    if (locator.name_matches !== undefined &&
        (new TextEncoder().encode(name).length > 4096 || !new RegExp(locator.name_matches, "u").test(name))) {
      return false;
    }
    for (const key of ["checked", "focused"]) {
      if (locator[key] !== undefined && axValue(node, key) !== locator[key]) return false;
    }
    return true;
  }

  ancestorMatches(node, locator, byId) {
    let parent = byId.get(node.parentId);
    while (parent) {
      if (locator.within && this.nodeMatchesTree(parent, locator.within, byId)) return true;
      if (locator.within_name_contains_any && locator.within_name_contains_any.some(
        (value) => normalized(axValue(parent, "name")).includes(normalized(value)),
      )) return true;
      parent = byId.get(parent.parentId);
    }
    return !locator.within && !locator.within_name_contains_any;
  }

  nodeMatchesTree(node, locator, byId) {
    return this.nodeMatches(node, locator) && this.ancestorMatches(node, locator, byId);
  }

  async findAX(locator, requireSingle) {
    const {nodes, byId} = await this.axTree();
    let matches = nodes.filter((node) => this.nodeMatchesTree(node, locator, byId));
    if (locator.ordinal !== undefined) matches = matches.slice(locator.ordinal, locator.ordinal + 1);
    if (!matches.length) fail("element-not-found");
    if ((requireSingle || locator.unique) && matches.length !== 1) fail("element-ambiguous");
    return matches;
  }

  async backendBox(backendNodeId) {
    if (!Number.isInteger(backendNodeId)) fail("element-has-no-dom-node");
    try {
      await this.command("DOM.scrollIntoViewIfNeeded", {backendNodeId});
    } catch (_error) {
      fail("element-scroll-failed");
    }
    const result = await this.command("DOM.getBoxModel", {backendNodeId});
    return boxCenter(result.model);
  }

  async clickPoint(point) {
    await this.command("Input.dispatchMouseEvent", {
      type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1,
    });
    await this.command("Input.dispatchMouseEvent", {
      type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1,
    });
  }

  async clickDOM(locator) {
    const target = await this.findDOM(locator);
    await this.command("DOM.scrollIntoViewIfNeeded", {nodeId: target.nodeId});
    const box = await this.command("DOM.getBoxModel", {nodeId: target.nodeId});
    await this.clickPoint(boxCenter(box.model));
  }

  async clickAX(locator) {
    const [node] = await this.findAX(locator, true);
    await this.clickPoint(await this.backendBox(node.backendDOMNodeId));
  }

  async focusAX(locator) {
    const [node] = await this.findAX(locator, true);
    if (!Number.isInteger(node.backendDOMNodeId)) fail("element-has-no-dom-node");
    await this.command("DOM.focus", {backendNodeId: node.backendDOMNodeId});
  }

  async dispatchKeyChord(keys) {
    const definitions = keys.map((key) => keyDefinition(key, this.platform));
    let modifiers = 0;
    for (const definition of definitions) {
      modifiers |= definition.modifier || 0;
      await this.command("Input.dispatchKeyEvent", {
        type: "rawKeyDown", key: definition.key, code: definition.code,
        windowsVirtualKeyCode: definition.vk, nativeVirtualKeyCode: definition.vk,
        modifiers,
      });
    }
    for (const definition of [...definitions].reverse()) {
      await this.command("Input.dispatchKeyEvent", {
        type: "keyUp", key: definition.key, code: definition.code,
        windowsVirtualKeyCode: definition.vk, nativeVirtualKeyCode: definition.vk,
        modifiers,
      });
      modifiers &= ~(definition.modifier || 0);
    }
  }

  async insertPrivateText(slot, replaceAll) {
    const text = this.privateValues[slot];
    if (typeof text !== "string") fail("private-slot-missing");
    if (replaceAll) await this.dispatchKeyChord(["platform-primary", "a"]);
    await this.command("Input.insertText", {text});
  }

  async assertFocusedPrivateValue(slot) {
    const expected = this.privateValues[slot];
    const {nodes} = await this.axTree();
    const matching = nodes.filter((node) =>
      axValue(node, "focused") === true && String(axValue(node, "value") ?? "") === expected);
    if (matching.length !== 1) {
      fail("private-value-mismatch");
    }
  }

  async assertAXPrivateSHA256(action) {
    const expected = this.privateValues[action.slot];
    if (typeof expected !== "string" || !/^[a-f0-9]{64}$/u.test(expected)) {
      fail("private-hash-invalid");
    }
    const matches = await this.findAX(action.locator, false);
    const snapshot = matches
      .slice(0, action.max_items)
      .map((node) => this.extractNode(node, action.fields));
    const canonical = snapshot.map((row) => Object.fromEntries(
      Object.keys(row).sort().map((key) => [key, row[key]]),
    ));
    const bytes = new TextEncoder().encode(JSON.stringify(canonical));
    if (bytes.length > MAX_PRIVATE_RESULTS_BYTES) fail("private-result-too-large");
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const actual = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (actual !== expected) fail("private-snapshot-mismatch");
  }

  safeExtractedValue(value) {
    if (typeof value === "string" && new TextEncoder().encode(value).length > MAX_EXTRACTED_FIELD_BYTES) {
      fail("private-result-too-large");
    }
    if (value !== null && value !== undefined && !["string", "number", "boolean"].includes(typeof value)) {
      fail("private-result-invalid");
    }
    return value ?? null;
  }

  extractNode(node, fields) {
    return Object.fromEntries(fields.map((field) => [field, this.safeExtractedValue(axValue(node, field))]));
  }

  async extractAX(action) {
    const matches = await this.findAX(action.locator, false);
    this.privateResults[action.private_result] = matches
      .slice(0, action.max_items)
      .map((node) => this.extractNode(node, action.fields));
    this.assertPrivateResultsBounded(action.private_result);
  }

  async collectAXByScrolling(action) {
    const rows = [];
    const seen = new Set();
    let stable = 0;
    let encodedBytes = 2;
    for (let round = 0; round <= action.max_scrolls; round += 1) {
      this.checkDeadline();
      const matches = await this.findAX(action.locator, false);
      let added = 0;
      for (const node of matches) {
        const row = this.extractNode(node, action.fields);
        const identity = JSON.stringify(action.dedupe_fields.map((field) => row[field]));
        if (seen.has(identity)) continue;
        seen.add(identity);
        const rowBytes = new TextEncoder().encode(JSON.stringify(row)).length + 1;
        if (encodedBytes + rowBytes > MAX_PRIVATE_RESULTS_BYTES) fail("private-result-too-large");
        encodedBytes += rowBytes;
        rows.push(row);
        added += 1;
        if (rows.length >= action.max_items) break;
      }
      if (rows.length >= action.max_items) break;
      stable = added === 0 ? stable + 1 : 0;
      if (round >= action.max_scrolls || stable >= action.stable_rounds) break;
      const [anchor] = await this.findAX(action.scroll_anchor, true);
      await this.scrollViewport(action, await this.backendBox(anchor.backendDOMNodeId));
      await sleep(action.settle_ms);
      await this.assertExactTarget();
    }
    this.privateResults[action.private_result] = rows;
    this.assertPrivateResultsBounded(action.private_result);
  }

  assertPrivateResultsBounded(field) {
    if (new TextEncoder().encode(JSON.stringify(this.privateResults)).length > MAX_PRIVATE_RESULTS_BYTES) {
      delete this.privateResults[field];
      fail("private-result-too-large");
    }
  }

  async captureViewport(action) {
    const result = await this.command("Page.captureScreenshot", {
      format: "jpeg",
      quality: action.quality,
      fromSurface: true,
      captureBeyondViewport: false,
      optimizeForSpeed: true,
    });
    if (typeof result.data !== "string" || !result.data || result.data.length % 4 !== 0 ||
        !/^[A-Za-z0-9+/]*={0,2}$/u.test(result.data)) {
      fail("screenshot-invalid");
    }
    if (result.data.length > Math.ceil(action.max_bytes / 3) * 4 + 4) {
      fail("screenshot-too-large");
    }
    let size;
    try {
      size = atob(result.data).length;
    } catch (_error) {
      fail("screenshot-invalid");
    }
    if (size > action.max_bytes) fail("screenshot-too-large");
    this.privateResults[action.private_result] = {
      mime_type: "image/jpeg",
      data_base64: result.data,
    };
    this.assertPrivateResultsBounded(action.private_result);
  }

  async scrollViewport(action, point = {x: 1, y: 1}) {
    const deltaY = action.direction === "down" ? action.distance_px : -action.distance_px;
    await this.command("Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x: point.x,
      y: point.y,
      deltaX: 0,
      deltaY,
    });
  }

  handleLogEvent(source, method, parameters) {
    const capture = this.logCapture;
    if (!capture || source?.tabId !== this.tabId || method !== "Log.entryAdded") return;
    const entry = parameters?.entry;
    if (!entry || typeof entry !== "object" || typeof entry.source !== "string" ||
        typeof entry.level !== "string" || typeof entry.text !== "string") {
      capture.failed = "private-log-invalid";
      return;
    }
    if (capture.entries.length >= capture.maxEntries) {
      capture.truncated = true;
      return;
    }
    if (new TextEncoder().encode(entry.text).length > capture.maxTextBytes) {
      capture.truncated = true;
      return;
    }
    try {
      const row = {
        source: this.safeExtractedValue(entry.source),
        level: this.safeExtractedValue(entry.level),
        text: this.safeExtractedValue(entry.text),
        timestamp: this.safeExtractedValue(entry.timestamp),
        url: this.safeExtractedValue(entry.url),
        line_number: this.safeExtractedValue(entry.lineNumber),
      };
      const size = new TextEncoder().encode(JSON.stringify(row)).length + 1;
      if (capture.encodedBytes + size > MAX_PRIVATE_RESULTS_BYTES) {
        capture.truncated = true;
        return;
      }
      capture.encodedBytes += size;
      capture.entries.push(row);
    } catch (_error) {
      capture.failed = "private-log-invalid";
    }
  }

  async startLogCapture(action) {
    if (!this.attached || this.logCapture || !this.chrome.debugger?.onEvent?.addListener) {
      fail("log-capture-state-invalid");
    }
    const capture = {
      privateResult: action.private_result,
      maxEntries: action.max_entries,
      maxTextBytes: action.max_text_bytes,
      entries: [],
      encodedBytes: 2,
      truncated: false,
      failed: null,
      listener: null,
    };
    capture.listener = (source, method, parameters) => this.handleLogEvent(source, method, parameters);
    this.logCapture = capture;
    this.chrome.debugger.onEvent.addListener(capture.listener);
    try {
      await this.command("Log.enable", {});
    } catch (error) {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
      this.logCapture = null;
      throw error;
    }
  }

  async stopLogCapture(bestEffort) {
    const capture = this.logCapture;
    if (!capture) {
      if (bestEffort) return;
      fail("log-capture-state-invalid");
    }
    this.logCapture = null;
    try {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
    } catch (_error) {
      if (!bestEffort) fail("log-capture-cleanup-failed");
    }
    try {
      await this.command("Log.disable", {});
    } catch (_error) {
      if (!bestEffort) fail("log-capture-cleanup-failed");
    }
    if (bestEffort) return;
    if (capture.failed) fail(capture.failed);
    this.privateResults[capture.privateResult] = {
      entries: capture.entries,
      truncated: capture.truncated,
    };
    this.assertPrivateResultsBounded(capture.privateResult);
  }

  requestCaptureFits(capture) {
    const value = {entries: capture.entries, truncated: capture.truncated};
    return new TextEncoder().encode(JSON.stringify(value)).length <= MAX_PRIVATE_RESULTS_BYTES;
  }

  privateRequestUrl(rawUrl, maximumBytes) {
    if (typeof rawUrl !== "string") fail("private-request-invalid");
    let url;
    try {
      url = new URL(rawUrl);
    } catch (_error) {
      fail("private-request-invalid");
    }
    if (!["http:", "https:"].includes(url.protocol)) return null;
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    const value = url.href;
    if (new TextEncoder().encode(value).length > maximumBytes) return null;
    return value;
  }

  handleRequestEvent(source, method, parameters) {
    const capture = this.requestCapture;
    if (!capture || source?.tabId !== this.tabId || ![
      "Network.requestWillBeSent", "Network.responseReceived", "Network.loadingFailed",
    ].includes(method)) return;
    const requestId = parameters?.requestId;
    if (typeof requestId !== "string" || !requestId ||
        new TextEncoder().encode(requestId).length > 512) {
      capture.failed = "private-request-invalid";
      return;
    }
    try {
      if (method === "Network.requestWillBeSent") {
        const request = parameters.request;
        const url = this.privateRequestUrl(request?.url, capture.maxUrlBytes);
        if (url === null) {
          capture.truncated = true;
          return;
        }
        if (typeof request.method !== "string" || !/^[A-Z]{1,32}$/u.test(request.method) ||
            typeof parameters.type !== "string" ||
            new TextEncoder().encode(parameters.type).length > 64) {
          capture.failed = "private-request-invalid";
          return;
        }
        if (capture.entries.length >= capture.maxEntries) {
          capture.truncated = true;
          return;
        }
        const row = {
          method: request.method,
          url,
          resource_type: parameters.type,
          timestamp: this.safeExtractedValue(parameters.timestamp),
          status: null,
          mime_type: null,
          from_disk_cache: false,
          failed: false,
          error_text: null,
          canceled: false,
        };
        capture.entries.push(row);
        if (!this.requestCaptureFits(capture)) {
          capture.entries.pop();
          capture.truncated = true;
          return;
        }
        capture.byRequestId.set(requestId, capture.entries.length - 1);
        return;
      }
      const index = capture.byRequestId.get(requestId);
      if (!Number.isInteger(index)) return;
      const row = capture.entries[index];
      const prior = structuredClone(row);
      if (method === "Network.responseReceived") {
        const response = parameters.response;
        if (!response || typeof response !== "object" ||
            typeof response.status !== "number" || !Number.isFinite(response.status) ||
            response.status < 0 || response.status > 999 ||
            typeof response.mimeType !== "string" ||
            new TextEncoder().encode(response.mimeType).length > 1024 ||
            typeof response.fromDiskCache !== "boolean") {
          capture.failed = "private-request-invalid";
          return;
        }
        row.status = response.status;
        row.mime_type = response.mimeType;
        row.from_disk_cache = response.fromDiskCache;
      } else {
        const errorText = parameters.errorText;
        if (typeof errorText !== "string" ||
            new TextEncoder().encode(errorText).length > capture.maxUrlBytes ||
            (parameters.canceled !== undefined && typeof parameters.canceled !== "boolean")) {
          capture.failed = "private-request-invalid";
          return;
        }
        row.failed = true;
        row.error_text = errorText;
        row.canceled = parameters.canceled === true;
      }
      if (!this.requestCaptureFits(capture)) {
        capture.entries[index] = prior;
        capture.truncated = true;
      }
    } catch (_error) {
      capture.failed = "private-request-invalid";
    }
  }

  async startRequestCapture(action) {
    if (!this.attached || this.requestCapture || !this.chrome.debugger?.onEvent?.addListener) {
      fail("request-capture-state-invalid");
    }
    const capture = {
      privateResult: action.private_result,
      maxEntries: action.max_entries,
      maxUrlBytes: action.max_url_bytes,
      entries: [],
      byRequestId: new Map(),
      truncated: false,
      failed: null,
      listener: null,
    };
    capture.listener = (source, method, parameters) => this.handleRequestEvent(source, method, parameters);
    this.requestCapture = capture;
    this.chrome.debugger.onEvent.addListener(capture.listener);
    try {
      await this.command("Network.enable", {});
    } catch (error) {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
      this.requestCapture = null;
      throw error;
    }
  }

  async stopRequestCapture(bestEffort) {
    const capture = this.requestCapture;
    if (!capture) {
      if (bestEffort) return;
      fail("request-capture-state-invalid");
    }
    this.requestCapture = null;
    try {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
    } catch (_error) {
      if (!bestEffort) fail("request-capture-cleanup-failed");
    }
    try {
      await this.command("Network.disable", {});
    } catch (_error) {
      if (!bestEffort) fail("request-capture-cleanup-failed");
    }
    if (bestEffort) return;
    if (capture.failed) fail(capture.failed);
    this.privateResults[capture.privateResult] = {
      entries: capture.entries,
      truncated: capture.truncated,
    };
    this.assertPrivateResultsBounded(capture.privateResult);
  }

  privateConsoleArgument(argument, maximumBytes) {
    if (!argument || typeof argument !== "object" || !REMOTE_OBJECT_TYPES.has(argument.type)) {
      fail("private-console-invalid");
    }
    const subtype = argument.subtype === undefined ? null : argument.subtype;
    if (subtype !== null && (typeof subtype !== "string" ||
        !/^[a-z][a-z0-9-]{0,63}$/u.test(subtype))) {
      fail("private-console-invalid");
    }
    let value = null;
    let truncated = false;
    if (argument.type === "string") {
      if (typeof argument.value !== "string") fail("private-console-invalid");
      if (new TextEncoder().encode(argument.value).length > maximumBytes) truncated = true;
      else value = argument.value;
    } else if (argument.type === "number") {
      if (typeof argument.value === "number" && Number.isFinite(argument.value)) {
        value = argument.value;
      } else if (typeof argument.unserializableValue === "string" &&
          new TextEncoder().encode(argument.unserializableValue).length <= maximumBytes) {
        value = argument.unserializableValue;
      } else {
        fail("private-console-invalid");
      }
    } else if (argument.type === "boolean") {
      if (typeof argument.value !== "boolean") fail("private-console-invalid");
      value = argument.value;
    } else if (argument.type === "bigint") {
      if (typeof argument.unserializableValue !== "string") fail("private-console-invalid");
      if (new TextEncoder().encode(argument.unserializableValue).length > maximumBytes) truncated = true;
      else value = argument.unserializableValue;
    }
    return {value: {type: argument.type, subtype, value}, truncated};
  }

  handleConsoleEvent(source, method, parameters) {
    const capture = this.consoleCapture;
    if (!capture || source?.tabId !== this.tabId || method !== "Runtime.consoleAPICalled") return;
    if (!parameters || !CONSOLE_TYPES.has(parameters.type) || !Array.isArray(parameters.args) ||
        typeof parameters.timestamp !== "number" || !Number.isFinite(parameters.timestamp)) {
      capture.failed = "private-console-invalid";
      return;
    }
    if (capture.entries.length >= capture.maxEntries) {
      capture.truncated = true;
      return;
    }
    try {
      let argumentsTruncated = parameters.args.length > capture.maxArguments;
      const args = parameters.args.slice(0, capture.maxArguments).map((argument) => {
        const converted = this.privateConsoleArgument(argument, capture.maxArgumentBytes);
        argumentsTruncated ||= converted.truncated;
        return converted.value;
      });
      const row = {
        type: parameters.type,
        timestamp: parameters.timestamp,
        arguments: args,
        arguments_truncated: argumentsTruncated,
      };
      capture.entries.push(row);
      const value = {entries: capture.entries, truncated: capture.truncated};
      if (new TextEncoder().encode(JSON.stringify(value)).length > MAX_PRIVATE_RESULTS_BYTES) {
        capture.entries.pop();
        capture.truncated = true;
      }
    } catch (_error) {
      capture.failed = "private-console-invalid";
    }
  }

  async startConsoleCapture(action) {
    if (!this.attached || this.consoleCapture || !this.chrome.debugger?.onEvent?.addListener) {
      fail("console-capture-state-invalid");
    }
    const capture = {
      privateResult: action.private_result,
      maxEntries: action.max_entries,
      maxArguments: action.max_arguments,
      maxArgumentBytes: action.max_argument_bytes,
      entries: [],
      truncated: false,
      failed: null,
      listener: null,
    };
    capture.listener = (source, method, parameters) => this.handleConsoleEvent(source, method, parameters);
    this.consoleCapture = capture;
    this.chrome.debugger.onEvent.addListener(capture.listener);
    try {
      await this.command("Runtime.enable", {});
    } catch (error) {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
      this.consoleCapture = null;
      throw error;
    }
  }

  async stopConsoleCapture(bestEffort) {
    const capture = this.consoleCapture;
    if (!capture) {
      if (bestEffort) return;
      fail("console-capture-state-invalid");
    }
    this.consoleCapture = null;
    try {
      this.chrome.debugger.onEvent.removeListener(capture.listener);
    } catch (_error) {
      if (!bestEffort) fail("console-capture-cleanup-failed");
    }
    try {
      await this.command("Runtime.disable", {});
    } catch (_error) {
      if (!bestEffort) fail("console-capture-cleanup-failed");
    }
    if (bestEffort) return;
    if (capture.failed) fail(capture.failed);
    this.privateResults[capture.privateResult] = {
      entries: capture.entries,
      truncated: capture.truncated,
    };
    this.assertPrivateResultsBounded(capture.privateResult);
  }

  async beforeMutation() {
    if (this.program.capability !== "mutation" || this.mutationStarted) fail("mutation-state-invalid");
    const authorized = await this.requestMutation();
    this.checkDeadline();
    if (authorized !== true) fail("mutation-denied");
    await this.assertExactTarget();
    this.mutationStarted = true;
    this.onProgress({
      actionCount: this.actionCount,
      maxActions: this.program.limits.max_actions,
      mutationStarted: true,
    });
  }
}

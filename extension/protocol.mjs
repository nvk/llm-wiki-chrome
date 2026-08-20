export const BROWSER_PROTOCOL = "llm-wiki-browser-executor/v1";

const ALLOWED_OPERATIONS = new Set([
  "open_or_focus_exact_url", "navigate_same_origin", "create_same_origin_tab", "navigate_history",
  "close_target_tab", "reload_exact_target", "assert_exact_target",
  "attach_debugger", "detach_debugger", "wait_ax", "wait_dom", "assert_ax",
  "first_success", "click_ax", "click_dom", "focus_ax", "hover_ax", "drag_ax",
  "select_ax_option", "scroll_ax_into_view", "dispatch_key_chord",
  "insert_private_text", "assert_ax_private_value", "wait_ax_private_value", "extract_ax",
  "assert_ax_private_sha256",
  "extract_ax_collection", "collect_ax_by_scrolling", "capture_viewport_private",
  "capture_region_private", "capture_full_page_private", "extract_ax_geometry",
  "capture_performance_private", "scroll_viewport", "wait_duration", "set_private_files",
  "start_download_capture", "stop_download_capture", "handle_dialog",
  "trigger_credential_broker", "start_log_capture", "stop_log_capture", "before_mutation",
  "start_request_capture", "stop_request_capture",
  "start_console_capture", "stop_console_capture",
]);
const FORBIDDEN_KEYS = new Set([
  "javascript", "script", "expression", "runtime_evaluate", "cdp_method",
  "cookie", "storage", "network",
]);
const TOP_LEVEL_KEYS = new Set([
  "protocol", "program_id", "program_sha256", "plan_sha256", "driver",
  "capability", "target", "limits", "private_slots", "actions", "result",
]);
const PUBLIC_RESULT_FIELDS = new Set([
  "status", "action_count", "mutation_started", "private_result_count",
]);
const MUTATION_ONLY = new Set([
  "insert_private_text", "before_mutation", "drag_ax", "select_ax_option",
  "set_private_files", "handle_dialog", "trigger_credential_broker",
  "create_same_origin_tab", "navigate_history", "close_target_tab",
]);
const LOCATOR_OPERATIONS = new Set([
  "wait_ax", "wait_dom", "assert_ax", "click_ax", "click_dom", "focus_ax", "hover_ax",
  "scroll_ax_into_view", "drag_ax", "select_ax_option", "set_private_files",
  "extract_ax_geometry",
  "extract_ax", "extract_ax_collection", "collect_ax_by_scrolling",
  "assert_ax_private_sha256",
]);
const DOM_LOCATOR_OPERATIONS = new Set(["wait_dom", "click_dom"]);
const AX_IDENTITY_KEYS = new Set([
  "role", "roles", "name", "name_contains", "name_contains_any", "name_matches",
  "within", "within_name_contains_any",
]);
const LOCATOR_KEYS = new Set([
  "selector", "role", "roles", "name", "name_contains", "name_contains_any",
  "name_matches", "within", "within_name_contains_any", "ordinal", "visible",
  "checked", "focused", "unique",
]);
const ACTION_KEYS = new Map([
  ["open_or_focus_exact_url", new Set(["op"])],
  ["navigate_same_origin", new Set(["op", "url"])],
  ["create_same_origin_tab", new Set(["op", "url"])],
  ["navigate_history", new Set(["op", "direction", "expected_url"])],
  ["close_target_tab", new Set(["op"])],
  ["reload_exact_target", new Set(["op", "ignore_cache"])],
  ["assert_exact_target", new Set(["op"])],
  ["attach_debugger", new Set(["op"])],
  ["detach_debugger", new Set(["op"])],
  ["before_mutation", new Set(["op"])],
  ["stop_log_capture", new Set(["op"])],
  ["stop_request_capture", new Set(["op"])],
  ["stop_console_capture", new Set(["op"])],
  ["wait_ax", new Set(["op", "locator", "timeout_ms"])],
  ["wait_dom", new Set(["op", "locator", "timeout_ms"])],
  ["assert_ax", new Set(["op", "locator"])],
  ["click_ax", new Set(["op", "locator"])],
  ["click_dom", new Set(["op", "locator"])],
  ["focus_ax", new Set(["op", "locator"])],
  ["hover_ax", new Set(["op", "locator"])],
  ["scroll_ax_into_view", new Set(["op", "locator"])],
  ["drag_ax", new Set(["op", "locator", "destination", "steps"])],
  ["select_ax_option", new Set(["op", "locator", "option_locator"])],
  ["dispatch_key_chord", new Set(["op", "keys"])],
  ["insert_private_text", new Set(["op", "slot", "replace_all"])],
  ["assert_ax_private_value", new Set(["op", "slot"])],
  ["wait_ax_private_value", new Set(["op", "slot", "timeout_ms"])],
  ["assert_ax_private_sha256", new Set(["op", "slot", "locator", "fields", "max_items"])],
  ["extract_ax", new Set(["op", "locator", "fields", "private_result", "max_items"])],
  ["extract_ax_collection", new Set(["op", "locator", "fields", "private_result", "max_items"])],
  ["collect_ax_by_scrolling", new Set([
    "op", "locator", "fields", "private_result", "max_items", "direction",
    "distance_px", "max_scrolls", "settle_ms", "dedupe_fields", "stable_rounds",
    "scroll_anchor",
  ])],
  ["capture_viewport_private", new Set(["op", "private_result", "quality", "max_bytes"])],
  ["capture_region_private", new Set([
    "op", "private_result", "quality", "max_bytes", "x", "y", "width", "height",
  ])],
  ["capture_full_page_private", new Set([
    "op", "private_result", "quality", "max_bytes", "max_width", "max_height",
  ])],
  ["extract_ax_geometry", new Set(["op", "locator", "private_result", "max_items"])],
  ["capture_performance_private", new Set(["op", "private_result", "max_metrics"])],
  ["scroll_viewport", new Set(["op", "direction", "distance_px"])],
  ["wait_duration", new Set(["op", "duration_ms"])],
  ["set_private_files", new Set(["op", "locator", "slot", "max_files"])],
  ["start_download_capture", new Set(["op", "private_result", "max_items"])],
  ["stop_download_capture", new Set(["op", "timeout_ms"])],
  ["handle_dialog", new Set(["op", "accept", "prompt_slot"])],
  ["trigger_credential_broker", new Set(["op", "broker"])],
  ["start_log_capture", new Set(["op", "private_result", "max_entries", "max_text_bytes"])],
  ["start_request_capture", new Set(["op", "private_result", "max_entries", "max_url_bytes"])],
  ["start_console_capture", new Set([
    "op", "private_result", "max_entries", "max_arguments", "max_argument_bytes",
  ])],
  ["first_success", new Set(["op", "branches"])],
]);
const EXTRACTION_FIELDS = new Set([
  "name", "role", "value", "description", "url", "checked", "focused",
]);
const SCROLL_DIRECTIONS = new Set(["up", "down"]);
const KEY_NAMES = new Set([
  "platform-primary", "control", "meta", "alt", "shift", "enter", "escape",
  "tab", "arrow-up", "arrow-down", "arrow-left", "arrow-right", "backspace",
  "delete", ..."abcdefghijklmnopqrstuvwxyz", ..."0123456789",
]);

function rejectUnknownKeys(value, allowed, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  if (!allowed || Object.keys(value).some((key) => !allowed.has(key))) {
    throw new Error(`${label} contains unsupported fields.`);
  }
}

function rejectForbiddenKeys(value) {
  if (Array.isArray(value)) {
    value.forEach(rejectForbiddenKeys);
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_KEYS.has(String(key).toLowerCase())) {
      throw new Error("The typed program contains a forbidden field.");
    }
    rejectForbiddenKeys(child);
  }
}

function validIdentifier(value, lowercase = false) {
  const pattern = lowercase
    ? /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/
    : /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$/;
  return typeof value === "string" && pattern.test(value);
}

function pathMatchesPrefix(path, prefix) {
  return path === prefix || (prefix.endsWith("/") ? path.startsWith(prefix) : path.startsWith(`${prefix}/`));
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]),
  );
}

export async function canonicalProgramHash(program) {
  const copy = structuredClone(program);
  delete copy.program_sha256;
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalValue(copy)));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function flattenActions(actions, depth = 0) {
  if (depth > 4) throw new Error("The typed program is nested too deeply.");
  if (!Array.isArray(actions)) throw new Error("Actions must be an array.");
  const flat = [];
  for (const action of actions) {
    if (!action || typeof action !== "object" || !ALLOWED_OPERATIONS.has(action.op)) {
      throw new Error("The typed program contains an unsupported action.");
    }
    flat.push(action);
    if (action.op === "first_success") {
      if (!Array.isArray(action.branches) || action.branches.length < 1 || action.branches.length > 4) {
        throw new Error("The typed program contains invalid branches.");
      }
      for (const branch of action.branches) {
        if (!Array.isArray(branch) || branch.length < 1) throw new Error("A branch is empty.");
        flat.push(...flattenActions(branch, depth + 1));
      }
    } else if (action.branches !== undefined) {
      throw new Error("Only first_success may contain branches.");
    }
  }
  return flat;
}

function validateLocator(locator, label, depth = 0) {
  if (depth > 2) throw new Error("A locator is nested too deeply.");
  rejectUnknownKeys(locator, LOCATOR_KEYS, label);
  if (Object.keys(locator).length < 1) throw new Error("A locator is empty.");
  if (locator.selector !== undefined &&
      (typeof locator.selector !== "string" || locator.selector.length < 1 || locator.selector.length > 16384)) {
    throw new Error("A locator selector is invalid.");
  }
  if (locator.role !== undefined && !validIdentifier(locator.role, true)) {
    throw new Error("A locator role is invalid.");
  }
  if (locator.roles !== undefined &&
      (!Array.isArray(locator.roles) || locator.roles.length < 1 || locator.roles.length > 8 ||
       new Set(locator.roles).size !== locator.roles.length ||
       locator.roles.some((role) => !validIdentifier(role, true)))) {
    throw new Error("Locator roles are invalid.");
  }
  for (const key of ["name", "name_contains", "name_matches"]) {
    if (locator[key] !== undefined &&
        (typeof locator[key] !== "string" || locator[key].length < 1 || locator[key].length > 16384)) {
      throw new Error("A locator name predicate is invalid.");
    }
  }
  if (locator.name_matches !== undefined) {
    const pattern = locator.name_matches;
    if (new TextEncoder().encode(pattern).length > 256 || /[(){}]/u.test(pattern) ||
        /(?:[+*?]){2,}/u.test(pattern) || /\\(?:[1-9]|k[<{])/u.test(pattern)) {
      throw new Error("A locator regex is outside the safe subset.");
    }
    try {
      new RegExp(pattern, "u");
    } catch (_error) {
      throw new Error("A locator regex is invalid.");
    }
  }
  for (const key of ["name_contains_any", "within_name_contains_any"]) {
    if (locator[key] !== undefined &&
        (!Array.isArray(locator[key]) || locator[key].length < 1 || locator[key].length > 12 ||
         locator[key].some((item) => typeof item !== "string" || item.length < 1 || item.length > 512))) {
      throw new Error("A locator string list is invalid.");
    }
  }
  if (locator.ordinal !== undefined &&
      (!Number.isInteger(locator.ordinal) || locator.ordinal < 0 || locator.ordinal > 1000)) {
    throw new Error("A locator ordinal is invalid.");
  }
  for (const key of ["visible", "checked", "focused", "unique"]) {
    if (locator[key] !== undefined && typeof locator[key] !== "boolean") {
      throw new Error("A locator state predicate is invalid.");
    }
  }
  if (locator.within !== undefined) validateLocator(locator.within, `${label}.within`, depth + 1);
}

function validateAXLocatorShape(locator) {
  if (locator.selector !== undefined || locator.visible !== undefined) {
    throw new Error("AX locators do not accept DOM selector or visibility predicates.");
  }
  if (![...AX_IDENTITY_KEYS].some((key) => locator[key] !== undefined)) {
    throw new Error("AX locators require a semantic identity predicate.");
  }
  if (locator.within !== undefined) validateAXLocatorShape(locator.within);
}

function validateDOMLocatorShape(locator) {
  if (locator.selector === undefined || Object.keys(locator)
    .some((key) => !["selector", "visible"].includes(key))) {
    throw new Error("DOM locators require only a selector and optional visibility.");
  }
}

function assertPolicyUrl(rawUrl, target, initial = false) {
  if (typeof rawUrl !== "string" || rawUrl.length > 16384) {
    throw new Error("A browser URL is invalid.");
  }
  const url = new URL(rawUrl);
  if (url.protocol !== "https:" || url.username || url.password || (url.hash && !initial) ||
      url.origin !== target.origin ||
      !target.path_prefixes.some((prefix) => pathMatchesPrefix(url.pathname, prefix)) ||
      (initial && rawUrl !== target.url)) {
    throw new Error("The browser URL is outside the exact target policy.");
  }
}

function validateAction(action, program, index) {
  rejectUnknownKeys(action, ACTION_KEYS.get(action.op), `Action ${index}`);
  if (["navigate_same_origin", "create_same_origin_tab"].includes(action.op)) {
    assertPolicyUrl(action.url, program.target);
  }
  if (action.op === "navigate_history") {
    if (!["back", "forward"].includes(action.direction)) throw new Error("A history direction is invalid.");
    assertPolicyUrl(action.expected_url, program.target);
  }
  if (action.op === "reload_exact_target" && typeof action.ignore_cache !== "boolean") {
    throw new Error("A reload declaration is invalid.");
  }
  if (LOCATOR_OPERATIONS.has(action.op)) validateLocator(action.locator, `Action ${index} locator`);
  if (LOCATOR_OPERATIONS.has(action.op)) {
    if (DOM_LOCATOR_OPERATIONS.has(action.op)) validateDOMLocatorShape(action.locator);
    else validateAXLocatorShape(action.locator);
  }
  if (action.op === "drag_ax") {
    validateLocator(action.destination, `Action ${index} destination`);
    validateAXLocatorShape(action.destination);
    if (!Number.isInteger(action.steps) || action.steps < 2 || action.steps > 50) {
      throw new Error("A drag declaration is invalid.");
    }
  }
  if (action.op === "select_ax_option") {
    validateLocator(action.option_locator, `Action ${index} option locator`);
    validateAXLocatorShape(action.option_locator);
  }
  if (["wait_ax", "wait_dom", "wait_ax_private_value"].includes(action.op) &&
      (!Number.isInteger(action.timeout_ms) || action.timeout_ms < 50 || action.timeout_ms > 300000)) {
    throw new Error("An action timeout is invalid.");
  }
  if (action.op === "dispatch_key_chord" &&
      (!Array.isArray(action.keys) || action.keys.length < 1 || action.keys.length > 5 ||
       new Set(action.keys).size !== action.keys.length || action.keys.some((key) => !KEY_NAMES.has(key)))) {
    throw new Error("A key chord is invalid.");
  }
  if ([
    "insert_private_text", "assert_ax_private_value", "wait_ax_private_value",
    "assert_ax_private_sha256", "set_private_files",
  ].includes(action.op) &&
      !program.private_slots.includes(action.slot)) {
    throw new Error("An action references an undeclared private slot.");
  }
  if (action.op === "insert_private_text" && typeof action.replace_all !== "boolean") {
    throw new Error("A private insertion mode is invalid.");
  }
  if (action.op === "set_private_files" &&
      (!Number.isInteger(action.max_files) || action.max_files < 1 || action.max_files > 16)) {
    throw new Error("A private file declaration is invalid.");
  }
  if ([
    "extract_ax", "extract_ax_collection", "collect_ax_by_scrolling", "assert_ax_private_sha256",
  ].includes(action.op)) {
    const maximum = action.op === "extract_ax" ? 100 : 5000;
    if (!Array.isArray(action.fields) || action.fields.length < 1 ||
        new Set(action.fields).size !== action.fields.length ||
        action.fields.some((field) => !EXTRACTION_FIELDS.has(field)) ||
        (action.op !== "assert_ax_private_sha256" &&
          !program.result.private_fields.includes(action.private_result)) ||
        !Number.isInteger(action.max_items) || action.max_items < 1 || action.max_items > maximum) {
      throw new Error("A private extraction is invalid.");
    }
  }
  if (action.op === "collect_ax_by_scrolling") {
    validateLocator(action.scroll_anchor, `Action ${index} scroll anchor`);
    validateAXLocatorShape(action.scroll_anchor);
  }
  if (["capture_viewport_private", "capture_region_private", "capture_full_page_private"].includes(action.op) &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.quality) || action.quality < 10 || action.quality > 90 ||
       !Number.isInteger(action.max_bytes) || action.max_bytes < 16384 || action.max_bytes > 262144)) {
    throw new Error("A private screenshot declaration is invalid.");
  }
  if (action.op === "capture_region_private" &&
      (![action.x, action.y].every((value) => typeof value === "number" && value >= 0 && value <= 100000) ||
       ![action.width, action.height].every((value) => typeof value === "number" && value >= 1 && value <= 10000))) {
    throw new Error("A screenshot region is invalid.");
  }
  if (action.op === "capture_full_page_private" &&
      (![action.max_width, action.max_height].every((value) =>
        Number.isInteger(value) && value >= 1 && value <= 20000))) {
    throw new Error("A full-page screenshot declaration is invalid.");
  }
  if (action.op === "extract_ax_geometry" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_items) || action.max_items < 1 || action.max_items > 500)) {
    throw new Error("A geometry extraction declaration is invalid.");
  }
  if (action.op === "capture_performance_private" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_metrics) || action.max_metrics < 1 || action.max_metrics > 100)) {
    throw new Error("A performance capture declaration is invalid.");
  }
  if (["scroll_viewport", "collect_ax_by_scrolling"].includes(action.op) &&
      (!SCROLL_DIRECTIONS.has(action.direction) ||
       !Number.isInteger(action.distance_px) || action.distance_px < 1 || action.distance_px > 10000)) {
    throw new Error("A viewport scroll declaration is invalid.");
  }
  if (action.op === "collect_ax_by_scrolling" &&
      (!Number.isInteger(action.max_scrolls) || action.max_scrolls < 1 ||
       action.max_scrolls > program.limits.max_repeat ||
       !Number.isInteger(action.settle_ms) || action.settle_ms < 50 || action.settle_ms > 3000 ||
       !Number.isInteger(action.stable_rounds) || action.stable_rounds < 1 ||
       action.stable_rounds > 3 || action.stable_rounds > action.max_scrolls ||
       !Array.isArray(action.dedupe_fields) || action.dedupe_fields.length < 1 ||
       action.dedupe_fields.length > action.fields.length ||
       new Set(action.dedupe_fields).size !== action.dedupe_fields.length ||
       action.dedupe_fields.some((field) => !action.fields.includes(field)))) {
    throw new Error("A scrolling collection declaration is invalid.");
  }
  if (action.op === "wait_duration" &&
      (!Number.isInteger(action.duration_ms) || action.duration_ms < 20 || action.duration_ms > 30000)) {
    throw new Error("A wait duration is invalid.");
  }
  if (action.op === "start_download_capture" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_items) || action.max_items < 1 || action.max_items > 16)) {
    throw new Error("A download capture declaration is invalid.");
  }
  if (action.op === "stop_download_capture" &&
      (!Number.isInteger(action.timeout_ms) || action.timeout_ms < 100 || action.timeout_ms > 120000)) {
    throw new Error("A download wait is invalid.");
  }
  if (action.op === "handle_dialog" &&
      (typeof action.accept !== "boolean" ||
       (action.prompt_slot !== null && action.prompt_slot !== undefined &&
        !program.private_slots.includes(action.prompt_slot)) ||
       (!action.accept && action.prompt_slot !== null && action.prompt_slot !== undefined))) {
    throw new Error("A dialog action is invalid.");
  }
  if (action.op === "trigger_credential_broker" &&
      !["onepassword", "browser-password-manager"].includes(action.broker)) {
    throw new Error("A credential broker is invalid.");
  }
  if (action.op === "start_log_capture" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_entries) || action.max_entries < 1 || action.max_entries > 500 ||
       !Number.isInteger(action.max_text_bytes) ||
       action.max_text_bytes < 256 || action.max_text_bytes > 16384)) {
    throw new Error("A private log capture declaration is invalid.");
  }
  if (action.op === "start_request_capture" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_entries) || action.max_entries < 1 || action.max_entries > 500 ||
       !Number.isInteger(action.max_url_bytes) ||
       action.max_url_bytes < 256 || action.max_url_bytes > 16384)) {
    throw new Error("A private request capture declaration is invalid.");
  }
  if (action.op === "start_console_capture" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.max_entries) || action.max_entries < 1 || action.max_entries > 500 ||
       !Number.isInteger(action.max_arguments) ||
       action.max_arguments < 1 || action.max_arguments > 20 ||
       !Number.isInteger(action.max_argument_bytes) ||
       action.max_argument_bytes < 256 || action.max_argument_bytes > 16384)) {
    throw new Error("A private console capture declaration is invalid.");
  }
}

export function validatePrivateValues(program, values) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    throw new Error("Private values must be an object.");
  }
  const expected = [...program.private_slots].sort();
  const actual = Object.keys(values).sort();
  if (JSON.stringify(expected) !== JSON.stringify(actual) ||
      actual.some((key) => typeof values[key] !== "string" ||
        new TextEncoder().encode(values[key]).length > 16384) ||
      new TextEncoder().encode(JSON.stringify(values)).length > 262144) {
    throw new Error("Private values do not match the declared private slots.");
  }
}

export async function validateProgram(program) {
  rejectForbiddenKeys(program);
  rejectUnknownKeys(program, TOP_LEVEL_KEYS, "The browser program");
  if (new TextEncoder().encode(JSON.stringify(program)).length > 262144 ||
      program.protocol !== BROWSER_PROTOCOL || !validIdentifier(program.program_id) ||
      !/^[a-f0-9]{64}$/.test(program.plan_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(program.program_sha256 || "")) {
    throw new Error("The browser program identity is invalid.");
  }
  if (program.program_sha256 !== await canonicalProgramHash(program)) {
    throw new Error("The browser program hash does not match.");
  }
  rejectUnknownKeys(program.driver, new Set(["id", "version"]), "The browser driver");
  if (!validIdentifier(program.driver.id, true) || !validIdentifier(program.driver.version)) {
    throw new Error("The browser driver identity is invalid.");
  }
  rejectUnknownKeys(
    program.target,
    new Set(["url", "origin", "path_prefixes", "collaboration_id"]),
    "The browser target",
  );
  if (!/^[a-f0-9]{64}$/.test(program.target.collaboration_id || "")) {
    throw new Error("The browser target requires an active collaboration id.");
  }
  if (!Array.isArray(program.target.path_prefixes) || program.target.path_prefixes.length < 1 ||
      program.target.path_prefixes.length > 8 ||
      new Set(program.target.path_prefixes).size !== program.target.path_prefixes.length ||
      program.target.path_prefixes.some((prefix) =>
        typeof prefix !== "string" || !prefix.startsWith("/") || prefix.includes("?") ||
        prefix.includes("#") || prefix.length > 2048)) {
    throw new Error("The browser target is invalid.");
  }
  assertPolicyUrl(program.target.url, program.target, true);
  rejectUnknownKeys(program.limits, new Set(["timeout_ms", "max_actions", "max_repeat"]), "Program limits");
  if (!Number.isInteger(program.limits.timeout_ms) || program.limits.timeout_ms < 1000 ||
      program.limits.timeout_ms > 300000 || !Number.isInteger(program.limits.max_actions) ||
      program.limits.max_actions < 1 || program.limits.max_actions > 200 ||
      !Number.isInteger(program.limits.max_repeat) || program.limits.max_repeat < 1 ||
      program.limits.max_repeat > 20 || !Array.isArray(program.actions) || program.actions.length < 1) {
    throw new Error("The browser program limits are invalid.");
  }
  if (!Array.isArray(program.private_slots) || program.private_slots.length > 32 ||
      new Set(program.private_slots).size !== program.private_slots.length ||
      program.private_slots.some((slot) => !/^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$/.test(slot))) {
    throw new Error("Private slots are invalid.");
  }
  rejectUnknownKeys(program.result, new Set(["public_fields", "private_fields"]), "Program result");
  if (!Array.isArray(program.result.public_fields) ||
      program.result.public_fields.some((field) => !PUBLIC_RESULT_FIELDS.has(field)) ||
      new Set(program.result.public_fields).size !== program.result.public_fields.length ||
      !Array.isArray(program.result.private_fields) || program.result.private_fields.length > 32 ||
      new Set(program.result.private_fields).size !== program.result.private_fields.length ||
      program.result.private_fields.some((field) =>
        !/^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$/.test(field))) {
    throw new Error("The browser result declaration is invalid.");
  }
  const flat = flattenActions(program.actions);
  if (flat.length > program.limits.max_actions) throw new Error("The browser program is too large.");
  flat.forEach((action, index) => validateAction(action, program, index));
  const operations = flat.map((action) => action.op);
  const topLevel = program.actions.map((action) => action.op);
  if (topLevel[0] !== "open_or_focus_exact_url" ||
      !["detach_debugger", "close_target_tab"].includes(topLevel.at(-1)) ||
      topLevel.filter((op) => op === "open_or_focus_exact_url").length !== 1 ||
      topLevel.filter((op) => op === "attach_debugger").length !== 1 ||
      topLevel.filter((op) => op === "detach_debugger").length !== 1 ||
      operations.filter((op) => op === "open_or_focus_exact_url").length !== 1 ||
      operations.filter((op) => op === "attach_debugger").length !== 1 ||
      operations.filter((op) => op === "detach_debugger").length !== 1 ||
      operations.indexOf("attach_debugger") >= operations.indexOf("detach_debugger") ||
      (topLevel.at(-1) === "close_target_tab" && topLevel.at(-2) !== "detach_debugger")) {
    throw new Error("The browser program lifecycle is invalid.");
  }
  const boundaries = operations.filter((operation) => operation === "before_mutation").length;
  if (program.capability === "read" && operations.some((operation) => MUTATION_ONLY.has(operation))) {
    throw new Error("A read program requested a mutation action.");
  }
  if (program.capability === "mutation" &&
      (boundaries !== 1 || topLevel.filter((op) => op === "before_mutation").length !== 1)) {
    throw new Error("A mutation program requires one governed boundary.");
  }
  if (!["read", "mutation"].includes(program.capability)) {
    throw new Error("The browser capability is invalid.");
  }
  if (program.capability === "mutation" &&
      topLevel.slice(topLevel.indexOf("before_mutation") + 1).includes("first_success")) {
    throw new Error("Mutation recovery branches must precede the mutation boundary.");
  }
  const logStarts = operations.filter((operation) => operation === "start_log_capture").length;
  const logStops = operations.filter((operation) => operation === "stop_log_capture").length;
  if (logStarts !== logStops || logStarts > 1 ||
      topLevel.filter((operation) => operation === "start_log_capture").length !== logStarts ||
      topLevel.filter((operation) => operation === "stop_log_capture").length !== logStops ||
      (logStarts === 1 && operations.indexOf("start_log_capture") >= operations.indexOf("stop_log_capture"))) {
    throw new Error("The private log capture lifecycle is invalid.");
  }
  const requestStarts = operations.filter((operation) => operation === "start_request_capture").length;
  const requestStops = operations.filter((operation) => operation === "stop_request_capture").length;
  if (requestStarts !== requestStops || requestStarts > 1 ||
      topLevel.filter((operation) => operation === "start_request_capture").length !== requestStarts ||
      topLevel.filter((operation) => operation === "stop_request_capture").length !== requestStops ||
      (requestStarts === 1 &&
       operations.indexOf("start_request_capture") >= operations.indexOf("stop_request_capture"))) {
    throw new Error("The private request capture lifecycle is invalid.");
  }
  const consoleStarts = operations.filter((operation) => operation === "start_console_capture").length;
  const consoleStops = operations.filter((operation) => operation === "stop_console_capture").length;
  if (consoleStarts !== consoleStops || consoleStarts > 1 ||
      topLevel.filter((operation) => operation === "start_console_capture").length !== consoleStarts ||
      topLevel.filter((operation) => operation === "stop_console_capture").length !== consoleStops ||
      (consoleStarts === 1 &&
       operations.indexOf("start_console_capture") >= operations.indexOf("stop_console_capture"))) {
    throw new Error("The private console capture lifecycle is invalid.");
  }
  const downloadStarts = operations.filter((operation) => operation === "start_download_capture").length;
  const downloadStops = operations.filter((operation) => operation === "stop_download_capture").length;
  if (downloadStarts !== downloadStops || downloadStarts > 1 ||
      topLevel.filter((operation) => operation === "start_download_capture").length !== downloadStarts ||
      topLevel.filter((operation) => operation === "stop_download_capture").length !== downloadStops ||
      (downloadStarts === 1 &&
       operations.indexOf("start_download_capture") >= operations.indexOf("stop_download_capture"))) {
    throw new Error("The private download capture lifecycle is invalid.");
  }
  const extracted = new Set(
    flat.filter((action) => [
      "extract_ax", "extract_ax_collection", "collect_ax_by_scrolling", "capture_viewport_private",
      "start_log_capture",
      "start_request_capture",
      "start_console_capture",
      "capture_region_private", "capture_full_page_private", "extract_ax_geometry",
      "capture_performance_private", "start_download_capture",
    ].includes(action.op))
      .map((action) => action.private_result),
  );
  if (extracted.size !== program.result.private_fields.length ||
      program.result.private_fields.some((field) => !extracted.has(field))) {
    throw new Error("Private results do not match extraction actions.");
  }
  return program;
}

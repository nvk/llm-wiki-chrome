export const BROWSER_PROTOCOL = "llm-wiki-browser-executor/v1";
export const APPROVED_ORIGINS = new Set(["https://docs.google.com", "https://x.com"]);

const ALLOWED_OPERATIONS = new Set([
  "open_or_focus_exact_url", "navigate_same_origin", "assert_exact_target",
  "attach_debugger", "detach_debugger", "wait_ax", "wait_dom", "assert_ax",
  "first_success", "click_ax", "click_dom", "focus_ax", "dispatch_key_chord",
  "insert_private_text", "assert_ax_private_value", "extract_ax",
  "extract_ax_collection", "collect_ax_by_scrolling", "capture_viewport_private",
  "scroll_viewport", "before_mutation",
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
const MUTATION_ONLY = new Set(["insert_private_text", "before_mutation"]);
const LOCATOR_OPERATIONS = new Set([
  "wait_ax", "wait_dom", "assert_ax", "click_ax", "click_dom", "focus_ax",
  "extract_ax", "extract_ax_collection", "collect_ax_by_scrolling",
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
  ["assert_exact_target", new Set(["op"])],
  ["attach_debugger", new Set(["op"])],
  ["detach_debugger", new Set(["op"])],
  ["before_mutation", new Set(["op"])],
  ["wait_ax", new Set(["op", "locator", "timeout_ms"])],
  ["wait_dom", new Set(["op", "locator", "timeout_ms"])],
  ["assert_ax", new Set(["op", "locator"])],
  ["click_ax", new Set(["op", "locator"])],
  ["click_dom", new Set(["op", "locator"])],
  ["focus_ax", new Set(["op", "locator"])],
  ["dispatch_key_chord", new Set(["op", "keys"])],
  ["insert_private_text", new Set(["op", "slot", "replace_all"])],
  ["assert_ax_private_value", new Set(["op", "slot"])],
  ["extract_ax", new Set(["op", "locator", "fields", "private_result", "max_items"])],
  ["extract_ax_collection", new Set(["op", "locator", "fields", "private_result", "max_items"])],
  ["collect_ax_by_scrolling", new Set([
    "op", "locator", "fields", "private_result", "max_items", "direction",
    "distance_px", "max_scrolls", "settle_ms", "dedupe_fields", "stable_rounds",
    "scroll_anchor",
  ])],
  ["capture_viewport_private", new Set(["op", "private_result", "quality", "max_bytes"])],
  ["scroll_viewport", new Set(["op", "direction", "distance_px"])],
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
  if (url.protocol !== "https:" || url.username || url.password || url.hash ||
      url.origin !== target.origin || !APPROVED_ORIGINS.has(url.origin) ||
      !target.path_prefixes.some((prefix) => pathMatchesPrefix(url.pathname, prefix)) ||
      (initial && rawUrl !== target.url)) {
    throw new Error("The browser URL is outside the exact target policy.");
  }
}

function validateAction(action, program, index) {
  rejectUnknownKeys(action, ACTION_KEYS.get(action.op), `Action ${index}`);
  if (action.op === "navigate_same_origin") assertPolicyUrl(action.url, program.target);
  if (LOCATOR_OPERATIONS.has(action.op)) validateLocator(action.locator, `Action ${index} locator`);
  if (LOCATOR_OPERATIONS.has(action.op)) {
    if (DOM_LOCATOR_OPERATIONS.has(action.op)) validateDOMLocatorShape(action.locator);
    else validateAXLocatorShape(action.locator);
  }
  if (["wait_ax", "wait_dom"].includes(action.op) &&
      (!Number.isInteger(action.timeout_ms) || action.timeout_ms < 50 || action.timeout_ms > 300000)) {
    throw new Error("An action timeout is invalid.");
  }
  if (action.op === "dispatch_key_chord" &&
      (!Array.isArray(action.keys) || action.keys.length < 1 || action.keys.length > 5 ||
       new Set(action.keys).size !== action.keys.length || action.keys.some((key) => !KEY_NAMES.has(key)))) {
    throw new Error("A key chord is invalid.");
  }
  if (["insert_private_text", "assert_ax_private_value"].includes(action.op) &&
      !program.private_slots.includes(action.slot)) {
    throw new Error("An action references an undeclared private slot.");
  }
  if (action.op === "insert_private_text" && typeof action.replace_all !== "boolean") {
    throw new Error("A private insertion mode is invalid.");
  }
  if (["extract_ax", "extract_ax_collection", "collect_ax_by_scrolling"].includes(action.op)) {
    const maximum = action.op === "extract_ax" ? 100 : 5000;
    if (!Array.isArray(action.fields) || action.fields.length < 1 ||
        new Set(action.fields).size !== action.fields.length ||
        action.fields.some((field) => !EXTRACTION_FIELDS.has(field)) ||
        !program.result.private_fields.includes(action.private_result) ||
        !Number.isInteger(action.max_items) || action.max_items < 1 || action.max_items > maximum) {
      throw new Error("A private extraction is invalid.");
    }
  }
  if (action.op === "collect_ax_by_scrolling") {
    validateLocator(action.scroll_anchor, `Action ${index} scroll anchor`);
    validateAXLocatorShape(action.scroll_anchor);
  }
  if (action.op === "capture_viewport_private" &&
      (!program.result.private_fields.includes(action.private_result) ||
       !Number.isInteger(action.quality) || action.quality < 10 || action.quality > 90 ||
       !Number.isInteger(action.max_bytes) || action.max_bytes < 16384 || action.max_bytes > 262144)) {
    throw new Error("A private screenshot declaration is invalid.");
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
  rejectUnknownKeys(program.target, new Set(["url", "origin", "path_prefixes"]), "The browser target");
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
  if (topLevel[0] !== "open_or_focus_exact_url" || topLevel.at(-1) !== "detach_debugger" ||
      topLevel.filter((op) => op === "open_or_focus_exact_url").length !== 1 ||
      topLevel.filter((op) => op === "attach_debugger").length !== 1 ||
      topLevel.filter((op) => op === "detach_debugger").length !== 1 ||
      operations.filter((op) => op === "open_or_focus_exact_url").length !== 1 ||
      operations.filter((op) => op === "attach_debugger").length !== 1 ||
      operations.filter((op) => op === "detach_debugger").length !== 1 ||
      operations.indexOf("attach_debugger") >= operations.indexOf("detach_debugger")) {
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
  const extracted = new Set(
    flat.filter((action) => [
      "extract_ax", "extract_ax_collection", "collect_ax_by_scrolling", "capture_viewport_private",
    ].includes(action.op))
      .map((action) => action.private_result),
  );
  if (extracted.size !== program.result.private_fields.length ||
      program.result.private_fields.some((field) => !extracted.has(field))) {
    throw new Error("Private results do not match extraction actions.");
  }
  return program;
}

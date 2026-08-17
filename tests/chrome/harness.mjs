import {BrowserExecutor, ExecutionError} from "./executor.mjs";
import {canonicalProgramHash, validateProgram} from "./protocol.mjs";

const root = document.documentElement;

function failClosed(error) {
  root.dataset.error = error instanceof ExecutionError ? error.code : "integration-failed";
  root.dataset.status = "error";
}

async function run() {
  const targetUrl = new URLSearchParams(globalThis.location.search).get("target");
  if (!targetUrl) throw new Error("missing-target");
  const target = new URL(targetUrl);
  const platform = await chrome.runtime.getPlatformInfo();
  const program = {
    protocol: "llm-wiki-browser-executor/v1",
    program_id: "synthetic-chrome-read-v1",
    program_sha256: "0".repeat(64),
    plan_sha256: "e".repeat(64),
    driver: {id: "synthetic-driver", version: "0.0.1"},
    capability: "read",
    target: {
      url: targetUrl,
      origin: target.origin,
      path_prefixes: [target.pathname],
      collaboration_id: "d".repeat(64),
    },
    limits: {timeout_ms: 30000, max_actions: 16, max_repeat: 3},
    private_slots: [],
    actions: [
      {op: "open_or_focus_exact_url"},
      {op: "attach_debugger"},
      {
        op: "start_log_capture",
        private_result: "page.browser_log",
        max_entries: 50,
        max_text_bytes: 4096,
      },
      {
        op: "start_request_capture",
        private_result: "page.requests",
        max_entries: 50,
        max_url_bytes: 4096,
      },
      {
        op: "start_console_capture",
        private_result: "page.console",
        max_entries: 50,
        max_arguments: 10,
        max_argument_bytes: 4096,
      },
      {op: "scroll_viewport", direction: "down", distance_px: 200},
      {
        op: "capture_viewport_private",
        private_result: "page.viewport",
        quality: 40,
        max_bytes: 262144,
      },
      {op: "stop_console_capture"},
      {op: "stop_request_capture"},
      {op: "stop_log_capture"},
      {op: "detach_debugger"},
    ],
    result: {
      public_fields: ["status", "action_count", "private_result_count"],
      private_fields: ["page.viewport", "page.browser_log", "page.requests", "page.console"],
    },
  };
  program.program_sha256 = await canonicalProgramHash(program);
  await validateProgram(program);

  const targetTab = await chrome.tabs.create({url: targetUrl, active: true});
  if (!Number.isInteger(targetTab.id)) throw new Error("missing-target-tab");
  const executor = new BrowserExecutor({
    chromeApi: chrome,
    platform: platform.os,
    targetTabId: targetTab.id,
  });
  const result = await executor.run(program, {}, async () => false);
  const capture = result.private["page.viewport"];
  if (capture?.mime_type !== "image/jpeg" || typeof capture.data_base64 !== "string") {
    throw new Error("missing-private-capture");
  }
  const bytes = atob(capture.data_base64).length;
  if (bytes < 1 || bytes > 262144) throw new Error("invalid-private-capture");
  if (!Array.isArray(result.private["page.requests"]?.entries)) {
    throw new Error("missing-private-requests");
  }
  if (!Array.isArray(result.private["page.console"]?.entries)) {
    throw new Error("missing-private-console");
  }

  // Only content-free counters cross the harness boundary. Discard the capture.
  result.private = {};
  root.dataset.actionCount = String(result.public.action_count);
  root.dataset.privateResultCount = String(result.public.private_result_count);
  root.dataset.status = "pass";
}

run().catch(failClosed);

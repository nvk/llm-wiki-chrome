# Claude-in-Chrome parity map

Reviewed 2026-08-17 against Anthropic's current Claude-in-Chrome help,
permissions, safety, and troubleshooting pages plus Chrome's extension/CDP
documentation.

"Parity" here means comparable browser capabilities behind llm-wiki's stricter
execution contract. It does not mean copying Claude's ambient chat, cloud
service, telemetry, model, broad default permissions, or natural-language
browser planner into this repository.

## Guardrails that remain different

- Targeted adapters compile deterministic versioned action programs.
- Every program is bound to an approved plan hash and one exact target.
- The executor accepts no natural-language tasks, arbitrary JavaScript, raw CDP
  methods, downloaded code, page-generated actions, or background browsing.
- Provider authorization, selectors, journals, idempotency, recovery policy,
  and final verification remain in targeted adapters.
- Page and extracted content use private result slots and never appear in
  status, errors, logs, the repository, or the wiki automatically.
- Production origins are reviewed explicitly rather than using `<all_urls>`.

## Capability matrix

| Claude-in-Chrome capability | Executor target | Status / gate |
|---|---|---|
| Read page structure, text, and link metadata | Bounded DOM and accessibility queries with private extraction | Live generic-tab snapshot passed; provider parity pending |
| Click and focus controls | Typed DOM/AX actions on the exact tab | Implemented in source; provider parity pending |
| Type and fill forms | Private slots, focused insertion, exact-value assertions | Implemented in source; provider parity pending |
| Navigate websites | Exact URL plus reviewed same-origin paths | Implemented in source; provider parity pending |
| Terminal/Desktop bridge | Stable Native Messaging host and private Unix socket | Live exact-tab bridge passed |
| Side-panel status | Content-free connector/job state only | Live connected-state gate passed |
| Direct agent tool surface | MCP tools for readiness, clicked-tab list, snapshot, screenshot, semantic click/type/key, and scroll | Live readiness, tab-list, snapshot, and scroll gates passed |
| Controlled-tab highlighting | Fixed green page outline/pill and per-tab `ON` action badge | Implemented in source; live-session gate pending |
| Screenshots / visual context | Bounded private viewport JPEG, no automatic model upload | Implemented in source; consumer parity pending |
| Scroll long pages and virtualized lists | Bounded typed scroll plus deduplicating AX collection on the exact tab | Live generic-tab scroll passed; X provider adoption pending |
| Browser log entries | Paired, bounded exact-tab CDP Log window with private-only scalar results | Implemented in source; live-browser gate pending |
| Multiple tabs | Up to 16 individually clicked active-tab grants; each job remains exact-target | Live two-origin routing gate passed |
| Request debugging | Paired exact-tab request metadata capture without queries, headers, bodies, cookies, IDs, or interception | Implemented in source; live-browser gate pending |
| Console API debugging | Paired exact-tab `Runtime.consoleAPICalled` capture with bounded scalar-only arguments and no evaluation or object dereferencing | Implemented in source; live-browser gate pending |
| Downloads and uploads | Registered file roots, typed operations, provider verification | Implemented; live transfer gate pending |
| Workflow recording / shortcuts | Record only typed actions, require review before provider compilation | Implemented as non-replayable in-memory draft |
| Scheduled/background tasks | In-memory read-only snapshot schedules; durable work uses external scheduler plus adapter journal | Implemented bounded slice |
| Notifications | Content-free completion/attention status | Implemented |
| Site allow/block controls | Exact manifest origins plus adapter registry policy | Current restrictive model |
| Manual/automatic permission modes | Public approval plus one-shot mutation boundary | Mutation phase |
| Prompt-injection classifiers | Treat page content as data; page content never becomes executable actions | Architectural control; evals still needed |
| Password-manager integration | Focus plus password-manager UI activation; executor never receives secrets | Implemented boundary; live 1Password gate pending |

## Current implementation slice

The current parity slice implements a bounded explicit multi-tab workspace,
private exact-URL discovery, per-tab and whole-workspace revocation, content-free
job progress and cancellation, exact-tab activation, same-origin/path
enforcement, typed DOM/AX queries, bounded waits and branches, private
extraction, clicks, focus, key chords, private text insertion, and the governed
mutation challenge. A local MCP server now exposes a fixed structured agent
inventory, so clicking the extension is sufficient to make the exact tab visible
and operable to a newly started configured agent session. It does not expose an
arbitrary program or scripting tool. Per-Chrome-instance private sockets are
aggregated by exact grant, avoiding last-process-wins behavior when several
Chrome windows or profiles have the extension loaded. A fixed content-blind
page marker makes every active grant visually obvious.
The toolbar action listener consumes the granted exact `Tab` and opens the side
panel synchronously in that same gesture. The connect button is only a
status/retry control, and its connected state confirms that the local agent
relay has been notified.

Deterministic tests cover signed-program validation, exact-origin tab queries,
DOM fallback, private AX extraction, private insertion, one mutation challenge,
denial, cancellation, target drift, paired browser-log, request-metadata, and
scalar-only console-API capture with cleanup, service-worker result filtering, and content-free
invalid-program failure. A separate Chrome-for-Testing harness is
ready to load a temporary unpacked copy, open a runtime-supplied exact approved
target, and prove real `chrome.tabs`, `chrome.debugger`, CDP screenshot,
cleanup, and private-result handling while returning only counters. The first
attempt was blocked before Chrome startup by the current local sandbox's macOS
Mach-service policy. A separate manual live gate has now passed: one explicitly
clicked public HTTPS tab was the only grant returned to the agent, a bounded AX
snapshot completed, and a bounded viewport scroll returned a successful
five-action receipt. A subsequent two-tab gate also passed: both distinct HTTPS
grants produced independent snapshots, a scroll routed only to the selected
second grant, and both collaboration IDs remained stable afterward. The
isolated harness and targeted-adapter shadow runs remain pending; this source
state has not been released as an upgrade.

The parity branch now also implements a controlled green tab group, exact
same-origin tab lifecycle and navigation, semantic waits/hover/select/drag,
region and capped full-page capture, geometry, performance diagnostics,
registered-root uploads/downloads, content-free notifications, authorization
modes, protected-action confirmation, password-manager UI activation, an
in-memory review-required workflow draft, and a provider-driver verification
helper. Only a one-shot, cancellable, in-memory read-only snapshot schedule is
available directly. Recurring or durable scheduling, scheduled mutations,
recovery journals, provider selectors, workflow compilation, and final
verification deliberately remain in targeted adapters.
Arbitrary sites, ambient tabs, raw JavaScript, raw CDP, and extension-owned
intent remain out of scope.

## Deferred Homebrew packaging

Package the shared connector only after the consolidated `0.1.0` candidate has
working typed execution, provider parity, upgrade/rollback tests, and explicit
release approval.

Preferred distribution:

- private tap rather than the public `nvk/tap`;
- formula `llm-wiki-browser-executor`;
- Python application and extension assets under `libexec`/`share` with stable
  `opt`-linked launcher paths;
- explicit `install`, `status`, `self-test`, and `uninstall` commands;
- no silent Chrome modification during `brew install`; and
- formula tests that use only temporary manifests and synthetic programs.

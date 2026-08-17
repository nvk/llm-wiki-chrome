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
| Read page structure, text, and link metadata | Bounded DOM and accessibility queries with private extraction | Implemented in source; provider parity pending |
| Click and focus controls | Typed DOM/AX actions on the exact tab | Implemented in source; provider parity pending |
| Type and fill forms | Private slots, focused insertion, exact-value assertions | Implemented in source; provider parity pending |
| Navigate websites | Exact URL plus reviewed same-origin paths | Implemented in source; provider parity pending |
| Terminal/Desktop bridge | Stable Native Messaging host and private Unix socket | Foundation complete |
| Side-panel status | Content-free connector/job state only | Foundation complete |
| Screenshots / visual context | Bounded private viewport JPEG, no automatic model upload | Implemented in source; consumer parity pending |
| Scroll long pages and virtualized lists | Bounded typed scroll plus deduplicating AX collection on the exact tab | Implemented in source; X provider adoption pending |
| Browser log entries | Paired, bounded exact-tab CDP Log window with private-only scalar results | Implemented in source; live-browser gate pending |
| Multiple tabs | Up to 16 individually clicked active-tab grants; each job remains exact-target | Implemented in source; live-browser gate pending |
| Request debugging | Paired exact-tab request metadata capture without queries, headers, bodies, cookies, IDs, or interception | Implemented in source; live-browser gate pending |
| Console API debugging | Paired exact-tab `Runtime.consoleAPICalled` capture with bounded scalar-only arguments and no evaluation or object dereferencing | Implemented in source; live-browser gate pending |
| Downloads and uploads | Registered file roots, typed operations, provider verification | Later explicit effect capability |
| Workflow recording / shortcuts | Record only typed actions, require review and signing before replay | Later targeted-adapter tooling |
| Scheduled/background tasks | External scheduler plus durable adapter journal | Later; never extension-owned intent |
| Notifications | Content-free completion/attention status | Later optional permission |
| Site allow/block controls | Exact manifest origins plus adapter registry policy | Current restrictive model |
| Manual/automatic permission modes | Public approval plus one-shot mutation boundary | Mutation phase |
| Prompt-injection classifiers | Treat page content as data; page content never becomes executable actions | Architectural control; evals still needed |
| Password-manager integration | Out of scope until a separate credential-broker design | Not planned |

## Current implementation slice

The current parity slice implements a bounded explicit multi-tab workspace,
private exact-URL discovery, per-tab and whole-workspace revocation, content-free
job progress and cancellation, exact-tab activation, same-origin/path
enforcement, typed DOM/AX queries, bounded waits and branches, private
extraction, clicks, focus, key chords, private text insertion, and the governed
mutation challenge. It retains the existing two reviewed production origins.

Deterministic tests cover signed-program validation, exact-origin tab queries,
DOM fallback, private AX extraction, private insertion, one mutation challenge,
denial, cancellation, target drift, paired browser-log, request-metadata, and
scalar-only console-API capture with cleanup, service-worker result filtering, and content-free
invalid-program failure. A separate Chrome-for-Testing harness is
ready to load a temporary unpacked copy, open a runtime-supplied exact approved
target, and prove real `chrome.tabs`, `chrome.debugger`, CDP screenshot,
cleanup, and private-result handling while returning only counters. The first
attempt was blocked before Chrome startup by the current local sandbox's macOS
Mach-service policy, so a successful real-browser result remains pending in an
allowed local test profile. Live targeted-adapter shadow runs remain the next
gate; this source state has not been released or installed as an upgrade.

Arbitrary sites, tab groups, downloads/uploads, recording, schedules, and
notifications are separate review events rather than
prerequisites for this slice. The viewport-only JPEG action was added without a
new permission: it is exact-target, quality- and byte-capped, declared as a
private result, and never persisted or uploaded by the executor.

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

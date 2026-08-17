# LLM Wiki Browser Execution Adapter

Private, content-free execution substrate for targeted llm-wiki adapters. It
provides one Chrome extension, one allowlisted Native Messaging host, a private
Unix-socket relay, and a versioned typed-job contract.

This is **not** a general browser agent. It does not accept natural-language
tasks, arbitrary JavaScript, raw CDP methods, downloaded code, ambient browser
access, or direct end-user routes. Provider-specific adapters still own routing,
authentication, planning, selectors, journals, recovery, idempotency, and final
read-back verification.

## Click-to-collaborate flow

The extension does not need persistent site access or per-page Chrome host
registration. The user opens an HTTPS page and clicks the extension action.
That Chrome user gesture creates a fresh ephemeral collaboration grant bound to
the exact tab, URL, and origin. The grant is revoked when the tab navigates,
closes, or the user chooses **Stop collaboration**.

Targeted adapters retrieve the active grant through the private native socket,
compile it into an exact typed program, and fail closed if the grant or page has
changed. The click authorizes exposing that page to bounded adapter reads; it
does not authorize an arbitrary write. Mutation jobs still require the exact
approved plan hash, the one-shot pre-mutation boundary, provider-specific
preconditions, and independent read-back verification.

Adapter code still has to be installed and trusted once. The collaboration
grant replaces per-resource registration and provider OAuth only for workflows
that can inspect and verify through the browser UI. A targeted adapter may keep
a first-party API as an optional stronger verification path.

Provider adapters use the private client directly:

```python
from browser_executor.client import BrowserExecutorClient

executor = BrowserExecutorClient()
collaboration = executor.current_collaboration()
if collaboration is None:
    raise RuntimeError("click the extension on the target page")

# Bind collaboration_id, url, and origin into the signed typed program.
result = executor.run(program, private_values=private_values)
```

## Development status

The current development branch extends the `0.0.1` foundation with the first
bounded execution slice:

- strict program hashing and validation;
- cross-language policy-decision tests for the Python client and MV3 validator;
- exact HTTPS target and bounded action declarations;
- click-created active-tab grants with no persistent host permissions;
- separate read and mutation capabilities;
- one governed mutation callback in the Python client;
- stable extension identity and exact native-host origin;
- private local state, short socket paths, message limits, and one active job;
- exact-tab activation and reviewed same-origin navigation;
- allowlisted DOM and accessibility-tree reads, waits, and private extraction;
- byte-capped private viewport JPEG capture with no executor-side persistence;
- bounded viewport scrolling, deduplicating long-list collection, and private
  AX link/description extraction;
- bounded exact-tab browser-log capture through private result slots;
- bounded exact-tab request metadata capture that strips query strings and
  ignores headers, bodies, cookies, initiators, and security details;
- bounded exact-tab console-API capture that retains only scalar arguments and
  never evaluates or dereferences remote objects;
- typed click, focus, key-chord, and private text-insertion actions;
- cancellation, target-focus drift detection, result-size limits, and
  best-effort debugger cleanup;
- one-shot pre-mutation authorization before a provider effect; and
- a route-free llm-wiki self-test manifest; and
- a content-free extension status panel with connected, running, authorization,
  and failure states.

This branch is not a release or an installed provider replacement. Targeted
adapter shadow runs, provider-owned verification, upgrade/rollback testing, and
explicit release approval remain required before a consolidated `0.1.0`.

## Repository boundary

Allowed tracked material:

- executable code and extension assets;
- protocol schemas and security documentation; and
- synthetic fixtures and deterministic tests.

Never commit real resource URLs or identifiers, page text, screenshots,
captures, plans, receipts, extracted results, cookies, credentials, browser
storage, or provider corpora. Runtime inputs and outputs stay in the targeted
adapter's separately controlled data plane and should remain in memory whenever
possible.

## Architecture

```text
targeted adapter
  -> retrieve exact user-created active-tab collaboration
  -> deterministic typed program + exact approved plan hash
  -> BrowserExecutorClient over a private Unix socket
  -> allowlisted Native Messaging host
  -> shared MV3 extension on the exact user-exposed tab
  -> one-shot before-mutation challenge when required
  -> private result slots returned only to the targeted adapter
```

Public llm-wiki may see this repository's route-free `self-test` adapter
manifest, but it never routes an external edit or research request directly to
the executor.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q adapter.py browser_executor tests
node --check extension/service-worker.js
node --check extension/protocol.mjs
node --check extension/executor.mjs
node --check extension/sidepanel.js
```

The deterministic suite is complemented by an isolated real-browser smoke
test. It requires a matching Chrome for Testing and ChromeDriver pair and an
exact approved read target supplied at runtime; it does not touch the normal
Chrome profile or print, persist, or return the captured viewport:

```sh
LLM_WIKI_BROWSER_E2E_TARGET_URL='<exact approved HTTPS target>' \
  .venv/bin/python tests/chrome/run_extension_e2e.py \
    --chrome '/path/to/Google Chrome for Testing' \
    --chromedriver '/path/to/chromedriver'
```

The harness copies the unpacked extension into a temporary directory, adds a
test-only extension page, runs the signed read program in headless Chrome, and
returns only content-free counters. Chrome binaries are not downloaded or
installed by the repository.

The self-test is content-free:

```sh
.venv/bin/python adapter.py describe
.venv/bin/python adapter.py execute --request /private/request.json \
  --response /private/response.json
```

`browser-install` writes an exact-origin Native Messaging manifest and launcher.
Use it only during an explicit installation or migration task. Loading the
unpacked extension, changing a normal Chrome profile, and upgrading an installed
copy are not part of the test suite and require explicit user direction.

## Security model

The executor validates a canonical program hash, approved plan hash, active
collaboration ID, fixed driver identity/version, exact target, capability, limits, action vocabulary,
private slots, and result allowlist independently in Python and the extension.
There are no persistent host permissions, `<all_urls>` access, or content
scripts; Chrome's `activeTab` grant is created only by the user's extension
click. The interpreter has a fixed CDP method
allowlist and does not accept `Runtime.evaluate`, raw methods, scripts, or
page-generated actions.

The fixed CDP allowlist also includes paired `Log.enable`/`Log.disable` and
`Network.enable`/`Network.disable` windows. The latter retains only bounded
private request method, origin/path, resource type, status, MIME, cache, and
failure scalars; it strips query strings and never retains headers, bodies,
cookies, initiators, security details, or request IDs. Neither capability
exposes raw diagnostic methods or request interception. A separate paired
`Runtime.enable`/`Runtime.disable` window retains only bounded private
`Runtime.consoleAPICalled` types, timestamps, and scalar arguments. It ignores
contexts, stacks, descriptions, previews, and object IDs and never allows
evaluation, compilation, function calls, script execution, or property access.
The executor is trusted local code, not an operating-system sandbox. Targeted
adapters remain responsible for authorizing every provider effect and proving
the provider's final state independently. See [SECURITY.md](SECURITY.md).

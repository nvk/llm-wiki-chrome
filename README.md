# LLM Wiki Browser Execution Adapter

Private, content-free execution substrate for targeted llm-wiki adapters. It
provides one Chrome extension, one allowlisted Native Messaging host, a private
Unix-socket relay, and a versioned typed-job contract.

This is **not** a general browser agent. It does not accept natural-language
tasks, arbitrary JavaScript, raw CDP methods, downloaded code, ambient browser
access, or direct end-user routes. Provider-specific adapters still own routing,
authentication, planning, selectors, journals, recovery, idempotency, and final
read-back verification.

## Development status

Source milestone `0.0.1` implements the Phase 1 foundation:

- strict program hashing and validation;
- exact HTTPS target and bounded action declarations;
- separate read and mutation capabilities;
- one governed mutation callback in the Python client;
- stable extension identity and exact native-host origin;
- private local state, short socket paths, message limits, and one active job;
- a route-free llm-wiki self-test manifest; and
- a content-free extension status panel.

The extension intentionally returns a content-free error for typed action jobs.
DOM/Accessibility execution begins in the next reviewed phase. Nothing in this
milestone should be installed as a working provider replacement.

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
  -> deterministic typed program + exact approved plan hash
  -> BrowserExecutorClient over a private Unix socket
  -> allowlisted Native Messaging host
  -> shared MV3 extension on one exact approved origin
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
node --check extension/sidepanel.js
```

The self-test is content-free:

```sh
.venv/bin/python adapter.py describe
.venv/bin/python adapter.py execute --request /private/request.json \
  --response /private/response.json
```

`browser-install` writes an exact-origin Native Messaging manifest and launcher.
Use it only during an explicit installation/migration task after the typed
interpreter and targeted-adapter parity gates pass. Loading the unpacked
extension or changing a normal Chrome profile is not part of the test suite.

## Security model

The executor validates a canonical program hash, approved plan hash, fixed
driver identity/version, exact target, capability, limits, action vocabulary,
private slots, and result allowlist independently in Python and the extension.
Production permissions are limited to explicitly reviewed origins; there is no
`<all_urls>` access or content script.

The executor is trusted local code, not an operating-system sandbox. Targeted
adapters remain responsible for authorizing every provider effect and proving
the provider's final state independently. See [SECURITY.md](SECURITY.md).

# Security and content boundary

This private repository contains code for a bounded local browser executor. It
does not make browser automation safe by itself and is not an authorization
boundary for provider effects.

Every job must be bound to a user-created active-tab collaboration ID, plan
hash, exact HTTPS target, explicit read or mutation capability, fixed driver
version, bounded action count, and deadline. The direct MCP surface publishes
only fixed structured operations and never accepts an arbitrary action program.
For consequential provider workflows, the targeted adapter remains responsible
for authorization, pre-mutation state checks, durable pending journals,
idempotency, and independent read-back verification.

The extension has no persistent host permissions. Each action click creates a
temporary grant for that exact active tab through Chrome's `activeTab`
permission. The action listener consumes that granted `Tab` and opens the panel
synchronously inside the same gesture; a runtime message never attempts to
manufacture a user gesture or open the panel. The bounded workspace contains at
most 16 explicitly clicked tabs.
The extension and private native relay keep grants in session memory, rotate a
grant on same-origin navigation, revoke it on cross-origin navigation or close,
and display only its hostname in the side panel. A local agent or targeted
adapter may retrieve exact targets only through the private user-owned socket.

Each Chrome extension process gets a random eight-hex socket suffix below the
configured private base path. The client accepts only the legacy exact base or
that strict suffix shape, validates owner and mode on every candidate, merges
only validated collaboration records, and requires exactly one owning relay
before routing a multi-process job. Stale or unreachable sockets are ignored.

The visible page-control marker is a packaged, fixed, noninteractive overlay.
It uses the click-created `activeTab` plus `scripting` permission, reads no page
content, exposes no messaging other than its fixed revoke signal, and is not a
manifest content script. Marker injection failure does not broaden or preserve
a grant.

The direct agent surface requires a collaboration ID obtained from
`browser_tabs` on every read or interaction. It supports only bounded AX
snapshots, viewport screenshots, semantic AX clicks, private text insertion,
allowlisted key chords, and viewport scrolling. It has no arbitrary program,
CSS selector, script, URL-navigation, cookie, storage, download, upload, or
credential tool. Direct click/type/key calls cross one internal mutation
boundary; they are intentionally unsuitable for effects that require a
provider-owned journal or transactional verification.
`browser_status` reports only connector readiness and the number of explicit
grants; it returns no URL, origin, identifier, or page content.

The extension independently validates the signed program and private-slot
shape. It accepts an HTTPS origin only when the program's collaboration ID,
exact URL, and origin match the live user grant. The extension activates that exact tab, aborts on
target or focus drift, uses only a
hardcoded DOM/Accessibility/Input/Page/Log/Network/Runtime CDP allowlist, and detaches the debugger
in a `finally` path. Waits retry only locator-not-ready conditions; cancellation,
deadline, debugger, and target errors fail immediately. Public results are
filtered to declared content-free counters, while bounded page data is returned
only through declared private result slots. Viewport scrolling and scrolling
collection are bounded, typed read actions; long-list collection is capped by
the program repeat, item, deadline, and private-result limits. Extracted link
URLs and descriptions remain private results.

Targeted adapters may bind a mutation to a private expected SHA-256 of a
bounded ordered AX projection. `assert_ax_private_sha256` recomputes that
projection on the exact collaboration tab before the governed boundary and
fails closed on drift. Neither the projection nor its expected hash appears in
public status or the side panel.

Browser diagnostics are limited to one paired `Log.enable`/`Log.disable`
window on the exact attached tab. Only bounded scalar fields are retained;
remote-object arguments and stack traces are ignored, overflow is marked only
inside the private result, and listeners are removed during failure cleanup.

Read-only request diagnostics are limited to one paired
`Network.enable`/`Network.disable` window on that same exact tab. The private
result retains bounded method, origin/path URL, resource type, timestamp,
status, MIME type, cache, and failure scalars. Query strings, credentials,
headers, request and response bodies, cookies, initiators, security details,
request IDs, WebSocket payloads, and interception are never retained or
exposed. The listener and Network domain are removed during failure cleanup.

Console diagnostics are limited to one paired
`Runtime.enable`/`Runtime.disable` window on that same exact tab and only the
`Runtime.consoleAPICalled` event. The private result retains bounded call type,
timestamp, and scalar arguments. Contexts, stack traces, object descriptions,
previews, object IDs, and non-scalar values are ignored. Evaluation,
compilation, function invocation, script execution, promise access, and remote
property access are absent from the fixed CDP method allowlist. The listener
and Runtime domain are removed during failure cleanup.

This design deliberately excludes arbitrary JavaScript, `Runtime.evaluate`, raw
CDP method names, ambient or unrelated-tab enumeration, page-authored actions, persistent host access,
and post-boundary fallback branches that could duplicate provider effects.

Cancellation is fail-closed at the next bounded action. It does not promise to
undo a provider mutation that has already started; the targeted adapter's
pending journal and read-back verification remain authoritative after that
boundary.

Never commit or log real resources, browser content, cookies, credentials,
captures, plans, receipts, or results. Report security concerns privately to the
repository owner.

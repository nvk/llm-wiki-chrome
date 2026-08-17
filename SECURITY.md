# Security and content boundary

This private repository contains code for a bounded local browser executor. It
does not make browser automation safe by itself and is not an authorization
boundary for provider effects.

Every job must be bound to an approved plan hash, exact HTTPS target, explicit
read or mutation capability, fixed driver version, bounded action count, and
deadline. The targeted adapter remains responsible for provider authorization,
pre-mutation state checks, durable pending journals, idempotency, and independent
read-back verification.

The extension independently validates the signed program and private-slot
shape. The Python and extension validators both reject origins outside the same
explicit production allowlist. The extension activates one exact tab, aborts on
target or focus drift, uses only a
hardcoded DOM/Accessibility/Input/Page CDP allowlist, and detaches the debugger
in a `finally` path. Waits retry only locator-not-ready conditions; cancellation,
deadline, debugger, and target errors fail immediately. Public results are
filtered to declared content-free counters, while bounded page data is returned
only through declared private result slots. Viewport scrolling and scrolling
collection are bounded, typed read actions; long-list collection is capped by
the program repeat, item, deadline, and private-result limits. Extracted link
URLs and descriptions remain private results.

This design deliberately excludes arbitrary JavaScript, `Runtime.evaluate`, raw
CDP method names, ambient tab enumeration, page-authored actions, broad origins,
and post-boundary fallback branches that could duplicate provider effects.

Never commit or log real resources, browser content, cookies, credentials,
captures, plans, receipts, or results. Report security concerns privately to the
repository owner.

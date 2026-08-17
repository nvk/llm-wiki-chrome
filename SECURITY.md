# Security and content boundary

This private repository contains code for a bounded local browser executor. It
does not make browser automation safe by itself and is not an authorization
boundary for provider effects.

Every job must be bound to an approved plan hash, exact HTTPS target, explicit
read or mutation capability, fixed driver version, bounded action count, and
deadline. The targeted adapter remains responsible for provider authorization,
pre-mutation state checks, durable pending journals, idempotency, and independent
read-back verification.

Never commit or log real resources, browser content, cookies, credentials,
captures, plans, receipts, or results. Report security concerns privately to the
repository owner.

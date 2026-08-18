# Public llm-wiki Browser Executor Instructions

This repository is a public execution tool, never a content store or a
general-purpose browser agent.

- Keep the repository public, content-free, and safe to clone and inspect.
- Commit only executable code, manifests, schemas, documentation, tests, and
  synthetic fixtures.
- Never commit real URLs, resource identifiers, page content, captures,
  credentials, cookies, browser storage, plans, receipts, or extracted results.
- Runtime inputs and outputs belong to explicitly controlled external data
  planes and should remain in memory whenever possible.
- The executor accepts only versioned typed jobs for one exact target. Never
  add arbitrary JavaScript, `Runtime.evaluate`, downloaded code, natural-language
  tasks, `<all_urls>`, ambient browsing, or unrelated-tab access.
- Provider routes, authentication, selectors, planning, journaling, recovery,
  and final verification remain in targeted adapters.
- The manifest must declare `writes_wiki: false` and no URL routes.
- Run all tests, inspect `git ls-files`, and scan for sensitive material before
  every push.
- Never create a release, tag, or installed upgrade without explicit user
  permission for that release.

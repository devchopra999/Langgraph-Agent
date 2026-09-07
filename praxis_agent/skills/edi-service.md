---
name: edi-service
tags: [edi, service-domain]
summary: Placeholder domain notes for the EDI service — replace with real details (key
  flows, external dependencies like Axis, gotchas) as they become available.
---

# EDI service notes (placeholder)

This file is a placeholder for service-specific domain knowledge about EDI. Replace this
content with real details, for example:

- What EDI is responsible for (transaction types, message formats it processes).
- External dependencies (e.g. Axis Bank API) — base URL config location, auth mechanism,
  known response quirks/edge cases worth mocking.
- Which other services call EDI or are called by it.
- Relevant database tables and what "transaction failed" vs "transaction succeeded" looks
  like at the row level.
- Common past production issues and their root causes, if known.

Until filled in, treat this as a signal that "EDI-specific context may exist — ask the
developer for domain specifics if the generic tools/logs/code aren't enough."

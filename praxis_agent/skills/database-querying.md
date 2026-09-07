---
name: database-querying
tags: [database, query, load, sql, locking]
summary: How to design and run a concurrency test against a service — finding the relevant
  SQL/queries, writing a small script, and executing it in parallel via execute_command.
---

# Database querying playbook

Use this when the bug/hypothesis involves anything related to database.

## Steps

1. **Discover the database service name.** Inspect the running environment first; query only the
   service-owned mysql/mongodb instance it reports rather than assuming a shared or standalone
   database name.
2. **Use query_database.** Send SQL for MySQL or a JavaScript expression against `db` for
   MongoDB. Record the relevant rows/results before and after the scenario.
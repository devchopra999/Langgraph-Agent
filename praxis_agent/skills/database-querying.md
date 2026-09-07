---
name: database-querying
tags: [database, query, load, sql, locking]
summary: How to design and run a concurrency test against a service — finding the relevant
  SQL/queries, writing a small script, and executing it in parallel via execute_command.
---

# Database querying playbook

Use this when the bug/hypothesis involves anything related to database.

## Steps

1. **Figure out the service you need to query** The service's name whose db you need to query must be given to you.
2. **Use query_database function** Use `query_database` to run query on the database.
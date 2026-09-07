---
name: fintech-ledger
tags: [fintech, wallet, ledger, transfers, deadlock, concurrency, idempotency, service-domain]
summary: Wallet and ledger contracts, opposite-direction transfer deadlock experiments,
  accounting invariants, and cross-service credit verification.
---

# fintech-ledger

Node.js/Express service backed by MySQL (Sequelize). Default port: `4002`.

## Opposite-direction transfer deadlocks

1. In an isolated executor environment, discover transaction boundaries, wallet lookup/lock
   order, SQL dialect, retry handling, and ledger-entry writes via `code_ask`. Do not assume
   row-lock ordering is the cause before observing the failing branch.
2. Create valid authenticated users and two wallets A and B through discovered APIs; seed enough
   funds for all intended debits using supported isolated fixtures. Record initial balances and
   entries in the ledger-owned database. Confirm A-to-B and B-to-A serial transfers work with
   the correct caller credentials before preparing fresh equivalent concurrency fixtures.
3. Use `execute_concurrent_requests` to synchronize mixed A-to-B and B-to-A requests in the same
   bounded burst. Retain direction, IDs, timestamps, responses, and latency; prove overlap.
   Repeat bounded rounds with controlled balances and fresh trial fixtures, adjusting concurrency
   based on evidence instead of asking for permission for another attempt.
4. Collect logs and available DB deadlock/lock-wait evidence even when requests return 500.
   Correlate affected transactions and lock acquisition with source. Distinguish deadlocks from
   insufficient funds, authentication errors, transport failures, or generic pool exhaustion.
5. Assert total funds are conserved according to the discovered fee rules, no partial transfer
   commits, each committed transfer has the expected debit/credit entries, balances reflect
   committed amounts, and requests make bounded progress. Reconcile uncertain outcomes from DB
   evidence rather than blindly resending a transfer.
6. For a requested fix, choose the change from the demonstrated cause; consider transaction
   scope, ordering, or safe retry semantics only where the evidence warrants them. Run existing
   targeted tests, `rebuild_service`, and check readiness. Replay the pinned workload against
   equally funded fresh wallets with unchanged assertions, then verify serial behavior and
   existing wallet-not-found/insufficient-funds contracts. No unexpected 500s alone is not proof
   of correct accounting. Check-only requests make no source edits.

## Cross-service credit verification

For payment callback investigations, follow `fintech-payments` and trace the actual credit
identity through both services. Verify committed credits, ledger entries, and wallet delta,
not merely successful HTTP acknowledgements. Do not presume that a payment-local uniqueness
constraint prevents repeated downstream credits or that the ledger already supports idempotency.

## Endpoints

These paths and auth labels are discovery hints. Inspect the runtime-selected branch for exact
payloads, ownership checks, credentials, schema, amounts/units, and dependencies; the table is
not an authentication specification. Never assume the internal credit endpoint's authorization
or idempotency behavior from this table.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/wallet/create` | Bearer JWT | Create a new wallet for the authenticated user |
| GET | `/wallet/:id` | Bearer JWT | Get a wallet by id |
| GET | `/wallet/:id/balance` | Bearer JWT | Get a wallet's current balance |
| GET | `/wallet/:id/entries` | Bearer JWT | List ledger entries for a wallet |
| POST | `/wallet/:id/credit` | none (internal, service-to-service) | Credit a wallet by a given amount; called by fintech-payments after a successful charge |
| POST | `/transfer` | Bearer JWT | Transfer funds from one wallet to another |

---
name: fintech-payments
tags: [fintech, payments, gateway, nexpay, ledger, webhook, concurrency, idempotency, service-domain]
summary: Payment flow discovery, duplicate callback experiments, and cross-service
  idempotency verification through committed payment and ledger evidence.
---

# fintech-payments

Node.js/Express service backed by MySQL (Sequelize). Default port: `4003`. Calls out to fintech-ledger (to credit wallets) and to the NexPay payment gateway.

## Duplicate callbacks and cross-service idempotency

1. **Prepare a real isolated flow.** Discover the initiate/callback code, auth service, wallet
   setup, gateway contract, and payment/transaction/ledger schemas. Use service APIs for valid
   users, wallet, and pending payment fixtures; mock the external gateway through the global
   mock workflow before initiation. Resolve actual returned IDs and reference fields rather
   than guessing. Derive callback payload and signing from branch code/config and fixture data;
   generate valid requests without exposing credentials in reports.
2. **Establish baselines.** Validate the flow using a separate serial-control payment. For the
   measured trial, create a fresh pending payment and record its transaction rows, wallet balance,
   and ledger entries. Define the one-success/one-credit invariant for the discovered contract,
   including amounts and fees. Do not use an already-completed payment as the initial race fixture.
3. **Deliver duplicates concurrently.** With `execute_concurrent_requests` or same-payload
   `run_load_test`, send bounded concurrent copies of the valid success callback for the **same**
   payment/provider reference. Keep that identity constant within the burst; renew only envelope
   timestamps/signatures if the actual verification contract requires it. Retain timing and
   response evidence. New references per request test separate payments, not duplicate delivery.
4. **Trace both commits.** Inspect payment rows, SUCCESS transaction counts, ledger credit
   entries, balance delta, and correlated logs after bounded settling. A duplicate-success-row
   report is reproduced only if rows demonstrate it; duplicate credit requires independent
   ledger evidence. A single payment transaction row or many 2xx acknowledgements does not prove
   single credit. Follow the downstream credit request identity and observed retry behavior.
5. **Diagnose without presupposing the fix.** Inspect callback state transitions, local atomicity,
   unique-key scope, credit request handling, ledger transaction boundaries, and the failure
   window between a credit commit and its acknowledgement/payment update. Determine whether
   concurrent callbacks and retries can cross those windows. Local locking, uniqueness, durable
   handoff/reconciliation, or downstream idempotency are candidates, not predetermined solutions.
   Do not claim cross-service exactly-once behavior from a local change or a mock acknowledgement.
   Test credit-success/acknowledgement-loss windows only with a documented supported mechanism;
   the global mock API does not supply invented delay/disconnect features. Report untested windows.
6. **Fix only when requested and replay.** Make a targeted evidence-backed change, including the
   downstream service if the demonstrated cause and authorized scope require it. Run existing
   regression tests, rebuild each edited service with `rebuild_service`, and check readiness.
   Create a fresh equivalent pending payment and wallet baseline for each independent before/after
   trial. Replay the pinned concurrent duplicate burst, then sequentially redeliver that trial's
   same callback. Require exactly one logical SUCCESS transaction and one committed credit/balance
   delta, with no extra credit after redelivery. Include distinct legitimate payments and
   contract-defined failure/signature-validation controls to detect overbroad deduplication.
7. **Report limits.** Preserve before/after evidence from both service-owned databases, source
   diff, workload parameters, and tested failure windows. Keep reproduced, fixed, and verified
   outcomes distinct. A check-only task must not edit source; incomplete downstream evidence is
   inconclusive, not a verified idempotency fix.

## Endpoints

Treat this table as discovery hints, not the selected branch's contract. Discover request
schemas, auth, callback signature verification, amount units, provider references, and service
dependencies before sending traffic. "None" does not establish that callbacks need no signature.
Fintech HTTP clients can call dependencies directly: use `mock-based-testing` to discover and
configure aliases/routing to the authoritative global mock, never assume a route intercepts them.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/payment/initiate` | Bearer JWT | Start a payment against a wallet via the NexPay gateway |
| GET | `/payment/:id` | Bearer JWT | Get a payment by id, including its transactions |
| GET | `/payment/wallet/:walletId` | Bearer JWT | List payments for a wallet |
| POST | `/payment/webhook/nexpay` | none (called by NexPay) | Receive async payment status updates from the NexPay gateway |

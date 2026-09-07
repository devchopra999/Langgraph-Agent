---
name: fintech-ledger
tags: [fintech, wallet, ledger, transfers, service-domain]
summary: Domain notes for the fintech wallet and ledger service, including balances, entries,
  credits, and inter-wallet transfers.
---

# fintech-ledger

Node.js/Express service backed by MySQL (Sequelize). Default port: `4002`.

## Endpoints

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

---
name: fintech-payments
tags: [fintech, payments, gateway, nexpay, ledger, service-domain]
summary: Domain notes for the fintech payment service, including NexPay charges, transaction
  status, webhook handling, and successful wallet credits.
---

# fintech-payments

Node.js/Express service backed by MySQL (Sequelize). Default port: `4003`. Calls out to fintech-ledger (to credit wallets) and to the NexPay payment gateway.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/payment/initiate` | Bearer JWT | Start a payment against a wallet via the NexPay gateway |
| GET | `/payment/:id` | Bearer JWT | Get a payment by id, including its transactions |
| GET | `/payment/wallet/:walletId` | Bearer JWT | List payments for a wallet |
| POST | `/payment/webhook/nexpay` | none (called by NexPay) | Receive async payment status updates from the NexPay gateway |

---
name: fintech-notifications
tags: [fintech, notifications, events, service-domain]
summary: Domain notes for the fintech notification service, including notification creation,
  user notification retrieval, unread counts, and read status updates.
---

# fintech-notifications

Node.js/Express service backed by MySQL (Sequelize). Default port: `4004`.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/notifications` | none (internal, service-to-service) | Create a notification; called by fintech-ledger/fintech-payments |
| GET | `/notification/api/v1/user/:userId` | none | List notifications for a user |
| GET | `/notification/api/v1/user/:userId/unread-count` | none | Get a user's unread notification count |
| PATCH | `/notification/api/v1/:id/read` | none | Mark a notification as read |

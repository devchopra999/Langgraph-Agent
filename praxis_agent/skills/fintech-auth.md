---
name: fintech-auth
tags: [fintech, authentication, jwt, user-management, service-domain]
summary: Domain notes for the fintech authentication service, including signup, signin, JWT
  issuance, and authenticated user lookup endpoints.
---

# fintech-auth

Node.js/Express service backed by MySQL (Sequelize). Default port: `4000`.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/auth/signup` | none | Create a new user account; returns the user and an access token |
| POST | `/auth/signin` | none | Authenticate with email/password; returns the user and an access token |
| GET | `/auth/me` | Bearer JWT | Get the current authenticated user's profile |
| GET | `/auth/users` | Bearer JWT | List all users |

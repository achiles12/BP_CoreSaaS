# Basic functionalities

## User Authentication and Account Management
   - Needed
## Organization / Tenant Management
   - Needed
   - plan for schema separated multi-tenant saas
   - MVP only, plan for 1 or 2 tenants. will increase if needed.
   - Tenant Resolution Phase 1: HEADER
                       Phase 2 or 3: Undecided, can be subdomain but i do not know. May not even reach phase 2. so do not bother
## Role-Based Access Control (RBAC)
   - Needed
   - plan for basic roles (Platform_Admin, Owner, Admin, Manager, Staff, User). Can be expanded as needed.
   - Roles/permissions tables per org, enforced in FastAPI dependencies.
   - can be maintained through DB Beaver and SQL
## Subscription and Billing Management
   - Can wait
   - prepare for Phase 3
## Dashboard and Analytics
   - Can wait
   - prepare for Phase 2 or 3
## Notifications and Communication
   - Needed
   - Phase 1: Mailpit (or MailHog) as a local SMTP sink. FastAPI sends to mailpit:1025 and you read the messages in a web UI.
   - Phase 2: can wait, undecided.

<--
  ┌────────────────────────────────┬────────────────────────────────────────┐
  │             Option             │                 Notes                  │
  ├────────────────────────────────┼────────────────────────────────────────┤
  │ SMTP relay (Amazon SES,        │ Cheapest and most reliable. Your app   │
  │ Postmark, Mailgun, Resend,     │ only needs SMTP credentials. SES is    │
  │ Brevo)                         │ about $0.10 per 1,000 emails.          │
  ├────────────────────────────────┼────────────────────────────────────────┤
  │ Self-hosted Postal             │ Full control, but you still need a     │
  │                                │ clean IP and the DNS setup above.      │
  ├────────────────────────────────┼────────────────────────────────────────┤
  │ Your own domain's existing     │                                        │
  │ mail provider (Google          │ Fine for low volume, with rate limits. │
  │ Workspace, Fastmail) over SMTP │                                        │
  └────────────────────────────────┴────────────────────────────────────────┘

keep it flexible:
  Make the sender a plain SMTP configuration (SMTP_HOST, SMTP_PORT, SMTP_USER,
  SMTP_PASSWORD, SMTP_FROM). Dev points at Mailpit, prod points at whichever
  relay you choose, and no code changes. Send through the background worker,
  with retries, so a slow SMTP server never blocks a request.

-->
## Audit Logs and Activity Tracking
   - Append-only `audit_log` table (org, actor, action, entity, diff JSONB, IP, timestamp), written via a FastAPI middleware/service layer; partition by month.
   - Write on a flat file on localhost. needs to be placed on a log directory
   - will be read via Putty or SFTP. no need to read from the app yet
   - Phase 3: read from app. may not even reach phase 3, do not bother
## File and Document Management
   - Needed
   - **MinIO** (S3-compatible, self-hosted) via `boto3`/`aioboto3`; presigned URLs for direct browser upload/download.
## Search, Filtering and Data Export
   - Needed
## Platform Administration
   - Needed
   - can us DB Beaver and SQL
   - can be handled from the backend by developer

<--
  ┌─────────────────┬───────────────────────────────────────────────────────┐
  │     Feature     │                  Suggested solution                   │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Authentication  │ In-app auth (FastAPI-Users/Authlib, Argon2, JWT in    │
  │                 │ httpOnly cookies), with Keycloak as a later upgrade   │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Tenants         │ Shared schema with Postgres row-level security        │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ RBAC            │ Permission checks in FastAPI, Casbin if the policies  │
  │                 │ get complex                                           │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Notifications   │ Redis plus a background worker (arq), email, and      │
  │                 │ in-app updates over server-sent events                │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Audit log       │ Append-only, partitioned Postgres table               │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Files           │ MinIO (S3-compatible) with ClamAV virus scanning      │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Search and      │ Postgres full-text search plus trigram matching,      │
  │ export          │ streamed CSV/XLSX export, Meilisearch later if needed │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ Admin           │ Superadmin area with an audited bypass of the tenant  │
  │                 │ rules                                                 │
  └─────────────────┴───────────────────────────────────────────────────────┘

-->

# Recommended Technology Stack
- suggest solutions that are self hosted on docker
- self-hosted

## Deployment
   - Docker Compose   
## Front End
   - Next.js + React
## Back End
   - Fast API
## UI
   - shadcn/ui
## Styling
   - Tailwind CSS
## Database
   - Postgres
## API State ??
   - TanStack Query
##  API Integration ??
   - OpenAPI-generated client
## Forms
   - React Hook Form + Zod
## Email
   - local host. dockerize if possible
   - Phase 1: Mailpit
   - Phase 2: Undecided. May not even reach phase2. do not bother.



# Architecture Overview

```
Idea 1:
            ┌────────────┐
 Browser ──▶│   Traefik  │ (TLS, routing)
            └─────┬──────┘
        ┌─────────┴──────────┐
        ▼                    ▼
  Next.js (React)       FastAPI  ──▶ Postgres (+ RLS, FTS)
                          │  │  └──▶ Redis ──▶ Celery/arq workers
                          │  └─────▶ MinIO (S3 files)
                          └────────▶ Mailpit/SMTP (email)


  - compose.yml (dev): no proxy, published ports, bind-mounted source for hot reload.
  - compose.prod.yml: adds Traefik (or Caddy) with TLS and routing.

Idea 2. Use this for now:
 Dev:   Browser ──▶ Next.js :3200 ──(rewrite /api/*)──▶ FastAPI :8200
 Prod:  Browser ──▶ Caddy (TLS) ──▶ Next.js / FastAPI

 FastAPI ──▶ Postgres (schema per tenant)
         ──▶ Redis ──▶ arq worker ──▶ SMTP (Mailpit in dev)
         ──▶ MinIO (files)
         ──▶ /var/log/app/audit/*.log (flat file)
```
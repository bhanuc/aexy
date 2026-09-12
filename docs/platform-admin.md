# Platform admin

Everything in Aexy is scoped to a workspace, except this. The platform admin
area is the view across every tenant: what the business is billing, whether it
is growing, and which workspaces are actually being used. It is staff tooling,
not a customer surface.

## Getting in

Access is by email allowlist. Set `ADMIN_EMAILS` on the backend to a
comma-separated list; a signed-in developer whose email is on it is a platform
admin, matched case-insensitively.

```bash
ADMIN_EMAILS=ops@example.com,founder@example.com
```

There is no database column and no UI for granting it, deliberately: changing
who can see every tenant's revenue should be a deployment, not a click. An
empty list means nobody is a platform admin, which is the safe default rather
than a broken one — but it also means the area is unreachable, including the
API, so set it before expecting the dashboard to load.

Platform admins get a **Platform admin** entry at the bottom of the sidebar.
Everyone else sees nothing and, if they type the URL, is sent back to their
dashboard.

## What each page is for

| Page | Question it answers |
|---|---|
| **Dashboard** (`/admin`) | What is the business doing today, and is it moving? |
| **Growth** (`/admin/growth`) | Signups, active workspaces, MRR, AI spend and cancellations over time |
| **Billing** (`/admin/billing`) | What is each workspace being charged, and what is the margin |
| **Workspaces** / **Users** | Who exists, on what plan, with how many members |
| **Plans** / **Plan overrides** | The price list, and per-workspace exceptions to it |
| **Invoices** | Manual and bank-transfer invoicing: raise, mark paid, void |
| **Email logs** / **Notifications** | Did the mail go out, and if not, why |
| **Feedback** / **AI benchmarking** | What people told us, and how the models are rating |

## The daily snapshot

Every platform figure used to be a live query, which meant each one described
this instant and nothing else. "What is MRR?" was answerable; "is it growing?"
was not, and could not be made answerable after the fact — nothing in the live
tables records that a workspace *was* active thirty days ago, and a plan's
price today is not the price it was billed at.

So one row is written per day into `platform_daily_stats` by a Temporal
schedule (`snapshot-platform-stats`, every 24 hours), and the dashboard reads
it.

What a row holds:

- **Growth** — total and newly created workspaces and people; workspaces active
  in the trailing 30 days.
- **Subscriptions** — MRR, paying and trialing workspaces, billable seats,
  cancellations, and a count by subscription status.
- **Money** — month-to-date revenue across every workspace, the provider cost
  behind it, the margin, and the split by plan tier and billing model.
- **AI** — requests, tokens, billed amount and provider cost for that day
  alone, broken down by provider.
- **Unpaid** — open and overdue invoices, by count and amount.

### Two definitions worth knowing

**Active** means somebody did something: created or changed a document, task
or project, posted a progress update, or spent AI budget in the trailing 30
days. The figure this replaced counted `WorkspaceMember.updated_at` — a
membership row's modification time, which is not activity at all.

**MRR** is recurring money only: the base fee plus the seats beyond those the
plan includes. Usage is deliberately excluded, so a heavy month of AI does not
read as subscription growth. Month-to-date revenue, which does include usage,
is the separate "Revenue this month" figure.

### What a backfilled day cannot tell you

`POST /platform-admin/stats/refresh?backfill_days=N` fills in the days before
the table existed. Only the parts that still carry their date can be
recovered: signups, cancellations and AI spend. Subscription state, seat
counts and the month-to-date bill describe *now*, so a past day is left at
zero and marked partial rather than stamped with today's numbers. The growth
charts break the line across those days instead of drawing a drop to zero that
never happened.

### Freshness

If the newest snapshot is more than 36 hours old, the dashboard says so at the
top. That usually means the Temporal worker is not running the analysis queue.
**Refresh** on the dashboard writes today's row immediately — useful on first
setup, or after changing a plan.

## Why the totals endpoint is fast now

`GET /platform-admin/billing/totals` used to loop every active workspace and
run a full billing breakdown per workspace, uncached, on every request — work
that grows with the tenant count. That is exactly what the nightly snapshot
does, so the endpoint reads one row instead. `?live=true` forces the old path,
and so does asking for a period the snapshot does not cover (`period=previous`).

## API

All of these require a platform admin.

```
GET  /api/v1/platform-admin/check                    is the caller one
GET  /api/v1/platform-admin/stats/overview           headline KPIs + deltas
GET  /api/v1/platform-admin/stats/series?days=90     the daily series
POST /api/v1/platform-admin/stats/refresh            write today's row now
GET  /api/v1/platform-admin/billing/totals           platform revenue and margin
GET  /api/v1/platform-admin/billing/summary          one row per workspace
GET  /api/v1/platform-admin/billing/breakdown        one workspace, line by line
GET  /api/v1/platform-admin/workspaces               every workspace
GET  /api/v1/platform-admin/users                    every developer
```

`/stats/overview` returns each figure as a small object carrying its value,
what it was on the comparison day, and the difference. When no snapshot
reaches that far back the previous value is `null` rather than `0`, because
"we do not know" and "it was zero" are different answers and only one of them
means the number is flat.

## Related

- [Stripe](./stripe.md) — subscriptions, webhooks and the payment side
- [Deployment](./guides/deployment.md) — where `ADMIN_EMAILS` goes in production

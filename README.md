# SaaS-Dependency-Health-Dashboard

A near-real-time data pipeline that polls public status APIs of 6 SaaS vendors, detects status changes, and surfaces uptime/incident metrics — the kind of internal tool a platform/SRE team builds to track dependency health.

<img src="powerbi/snapshot/SaaS Status Dashboard.png" alt="Dashboard">

## Architecture

```
EventBridge (every 10 min)
        │
        ▼
   AWS Lambda ──reads config──> Parameter Store
        │ writes raw JSON
        ▼
   S3 (raw landing zone)
        │
        ▼  Databricks Auto Loader (schema-enforced, SQS/SNS file notifications)
   Bronze  →  Silver  →  Gold        (Unity Catalog, Delta Lake)
                              │
                              ▼
                         Power BI
```

## Stack

| Layer | Tools |
|---|---|
| Ingestion | AWS Lambda, EventBridge Scheduler, Parameter Store |
| Storage / Security | S3, IAM (least-privilege roles, custom trust policies) |
| Processing | Databricks, PySpark, Auto Loader, Unity Catalog, Delta Lake |
| Modeling | SQL (window functions, CTEs), star schema |
| Visualization | Power BI |

## Vendors monitored

DigitalOcean, GitHub, Cloudflare, Zoom, OpenAI, Stripe — all expose a Statuspage.io-style `/api/v2/summary.json` endpoint, no auth required. **Stripe is intentionally left in the vendor list despite returning a 404** (it migrated off Statuspage.io) — kept to prove the pipeline's partial-failure handling and freshness checks catch a real, silent vendor-side API change rather than crash.

## Data layers

**Bronze** — raw JSON landed via Auto Loader, explicit nested schema (not inferred — an empty `incidents: []` array in early samples would have locked in the wrong type via inference).

**Silver** (5 tables) — `page_status`, `components`, `component_changes` (LAG window-function state-change detection), `incidents`, `incident_updates`. Vendor-reported incidents are deduplicated from repeated polls down to one row per incident via `ROW_NUMBER()`, with the full update timeline preserved separately.

**Gold** (7 fact tables + 2 dimensions, star schema) — `uptime_daily`, `incident_summary`, `vendor_incident_metrics`, `vendor_freshness`, `vendor_current_status`, `component_status_distribution`, `top_affected_components`, joined through `dim_vendor` / `dim_component`.

## Key engineering decisions

- **Planned maintenance ≠ outage.** Components in `under_maintenance` were initially counted as downtime, dragging uptime % to 0% for components doing nothing wrong. Fixed by computing two metrics side by side — strict uptime and maintenance-excluded uptime — rather than conflating the two.
- **Real incidents over inferred ones.** Initial incident detection relied purely on component status flips (noisy — large vendors flagged hundreds of brief regional blips). Added dedicated Silver tables built from vendors' own incident/timeline data for accurate MTTR instead.
- **Schema-on-write over inference.** Auto Loader was given an explicit schema rather than letting Spark infer one from sample data, after discovering an empty array field would have locked in the wrong type.
- **`NULL` ≠ `false`.** A cross-vendor schema inconsistency (one vendor's components had `group: null` instead of `true`/`false`) silently excluded that vendor from uptime calculations due to SQL's three-valued logic — fixed with `COALESCE`.
- **Least-privilege IAM throughout.** Separate roles for Lambda (S3 write-only, scoped to one prefix) and Databricks (Unity Catalog Storage Credential with per-query, audited cross-account access) — no shared or over-permissioned roles.

## Dashboard

3 KPI cards, month/vendor filtering, uptime trend line, incident-count bar chart, status-distribution donut, and a ranked view of longest-running incidents/maintenance windows — built on Gold tables via a Databricks SQL Warehouse connection.

## Repo structure

```
lambda/          → ingestion function
aws/             → IAM policies, trust policies
databricks/      → Bronze/Silver/Gold notebooks
powerbi/         → dashboard file + screenshots
docs/            → full project documentation
```

# Quote Request System

A reusable Flask starter for service businesses: a public marketing site, a quote/work
request intake, and an internal operations dashboard — with the optional parts switchable
per customer from a single config file.

Server-rendered HTML, no SPA, no build step. Multi-tenancy supports host-selected
databases, tenant-bound authentication, and tenant-specific branding, feature flags,
integrations, themes, rate-limit buckets, and partitioned upload/media storage in one
application instance, with persistent CLI provisioning and tenant-targeted migrations
and backup verification.

## What it does

**Public site**

- Preset-driven landing page, services, gallery, service area/directions, about,
  contact, FAQ, custom content pages, privacy and terms
- Quote request form with photo uploads and optional reCAPTCHA
- Schedule-work request form (when scheduling is enabled)
- 100-palette theme library, switchable at runtime from the admin
- Private customer photos are never served from the public static tree

**Admin**

- Request queue with filters, sorting and per-request detail
- Quote tracking (send, accept, decline) with draft autosave
- Customer records: contact fields, addresses, notes, photos, merge duplicates
- Scheduling: appointments, staff assignment, availability board, calendar
- Recurring work with generated events and impact previews
- Service catalogue and gallery/content management
- CSV/Excel import with previews
- Appearance picker for the theme library

## Module flags

Every optional module is a feature flag, configurable per tenant with deployment-wide
defaults for local development and single-client compatibility.

| Flag | Turns on |
|---|---|
| `ENABLE_SERVICES` | Service catalogue, public services page, service admin |
| `ENABLE_GALLERY` | Public gallery and gallery management |
| `ENABLE_SCHEDULING` | Schedule-work form and appointments |
| `ENABLE_STAFF_MANAGEMENT` | Staff records, availability board, assignment |
| `ENABLE_CUSTOMER_RECORDS` | Customer profiles, merge, history |
| `ENABLE_CALENDAR` | Month and day calendar views |
| `ENABLE_RECURRING_WORK` | Recurring plans and generated events |

Flags are enforced server-side, not just in the navigation: disabled modules cannot
be enabled by a public manifest, and a crafted POST creates nothing. Public manifest
page gates return 404 when disabled; existing module guards remain in force.

## Tech stack

Flask 3.1 · PostgreSQL (SQLite for tests) · SQLAlchemy + Flask-Migrate · Flask-Login ·
Flask-WTF · Jinja templates · one stylesheet · plain JavaScript in `app/static/js/` ·
pytest · GitHub Actions · gunicorn + nginx in production.

## Quick start (Windows)

```powershell
.\scripts\dev_setup.ps1
Copy-Item .env.example .env  # do not overwrite an existing .env
```

Use Python 3.12 for a fresh development environment. The bootstrap is repeatable,
works from any working directory, installs runtime/dev dependencies and Chromium, checks
dependency consistency, and runs a short readiness test set. If local execution policy
blocks the script, run `powershell -ExecutionPolicy Bypass -File scripts\dev_setup.ps1`
for that invocation only. It never edits `.env` or customer databases.

Edit `.env`: set a random `SECRET_KEY`, `DATABASE_URL=sqlite+pysqlite:///platform.sqlite3`
for local maintenance binding, and `TENANT_REGISTRY_FILE=tenants.json`. Keep email off
for demo data. Then use the venv interpreter (activation is optional):

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py tenant create demo --domain localhost --demo
.\.venv\Scripts\python.exe -m flask --app run.py create-admin --tenant demo --email owner@example.test
.\.venv\Scripts\python.exe -m flask --app run.py seed-demo --tenant demo
.\.venv\Scripts\python.exe -m flask --app run.py run
```

Open <http://localhost:5000/> and log in at `/admin` using the prompted password.
`localhost` is the configured domain here; `127.0.0.1` intentionally fails closed unless
also registered with repeated `--domain`. For production use separate PostgreSQL
databases, real domains, TLS, and the deployment runbook rather than this SQLite example.

If your database is already behind the migration head, `db upgrade` is the fix — the app
does not migrate itself on boot.

### Database

Native PostgreSQL:

```sql
CREATE USER quote_requests WITH PASSWORD 'change-me';
CREATE DATABASE quote_requests OWNER quote_requests;
```

Or start the bundled container: `docker-compose up -d`.

## Configuration

Deployment defaults live in `.env`; tenant records use a protected registry file or JSON
map (see `.env.example`). The settings that
change behaviour rather than just branding:

| Setting | Purpose |
|---|---|
| `SECRET_KEY` | Strong deployment signing key. Never reuse the dev key. |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` |
| `ENABLE_*` | Which modules this deployment includes |
| `RATE_LIMIT_*` | Anonymous form and login throttling |
| `EMAIL_ENABLED`, `SMTP_*` | Transactional email (Brevo-compatible); off by default |
| `RECAPTCHA_*` | Spam protection on the public forms |
| `TRUST_PROXY` | Set true only behind nginx, so client IPs and scheme are correct |
| `SITE_THEME` | Deploy-time default palette; customers can change it later in admin |
| `SITE_PRESET` | Public layout/content preset; defaults to `local_service_business` |
| `PUBLIC_PAGES_CONFIG` | Validated JSON manifest overriding the selected public preset |
| `SUPERADMIN_PASSWORD` | Platform master password; unset/blank disables the entire control prefix with 404 |
| `SUPERADMIN_HOST` | Optional dedicated control hostname; other hosts get 404 before CSRF/authentication |
| `SUPERADMIN_PATH` | Non-root control prefix; defaults to `/platform/control` |

### Public presets and manifest

Select `local_service_business` (backwards-compatible default, retaining optional
gallery/about/FAQ), `specialty_contractor` (trust/gallery emphasis and an Our Process
custom page), or `minimal_quote_funnel` (home/contact/quote intake). Presets do not
change CSS, themes, or master module flags. Tenant settings override deployment
defaults. CLI `tenant create --preset <name>` optionally stores `SITE_PRESET`;
omitting it preserves defaults or the selector in `--settings`. The dashboard offers
the same three choices and a JSON textarea showing **persisted overrides**, not the
merged preset. Omitted optional fields preserve existing values; a blank textarea or
`{}` resets manifest overrides. Invalid presets/manifests are rejected before database
creation or registry persistence. `--settings` must always be a JSON object.

`PUBLIC_PAGES_CONFIG` accepts an object with these fields (or a top-level ordered
list shorthand for `home_blocks`):

- `home_blocks`: ordered list of type strings or objects with a required `type`.
  Types: `hero`, `services_preview`, `trust_highlights`, `gallery_preview`,
  `service_area`, `quote_cta`, `custom_richtext`.
- `pages`: mapping keyed by `home`, `services`, `gallery`, `service_area`, `contact`,
  `about`, `faq`, `quote_request`, `schedule_work`; alternatively a replacement list
  of objects with `key` plus page fields. A replacement list disables omitted pages
  except home; explicitly disabling home is allowed. Page fields: `enabled`,
  `show_in_nav` (JSON booleans), `order` (integer), `title`, `nav_label`,
  `meta_description`, `text`, `hours`, `coverage`, `address`, `directions` (text), `sections`.
- `custom_pages`: replacement list of objects requiring an unreserved lowercase,
  hyphenated `slug` (at most 80 characters) and nonempty `title`; optional
  `nav_label`, `show_in_nav`, `enabled`, `order`, `meta_description`, `sections`
  and the same other page fields. Defaults: enabled, hidden from navigation,
  order 100, nav label from title, empty sections/meta description.
- `sections`: ordered list of objects requiring `type`: `hero`, `text`,
  `custom_richtext`, `feature_cards`, `checklist`, `faq`, `cta`, `quote_cta`.
  Aliases: `paragraphs` → `text`, `faq_accordion` → `faq`, `cta_banner` → `cta`.
  Blocks/sections accept `enabled`, `order`, and text fields `title`, `text`, `body`,
  `subtitle`, `eyebrow`, `cta_label`, `cta_url`, `hours`, `coverage`, `address`,
  `directions`; `paragraphs`/`checklist` are string lists, and `items` is a list of
  objects containing text fields `title`, `text`, `question`, `answer`, `label`, `url`.

Maps deep-merge; lists replace, and empty lists clear inherited content. `pages: []`
keeps only the implicit home page; `custom_pages: []` removes preset custom pages;
`home_blocks: []` (or a top-level `[]`) clears all home blocks. Navigation sorts by
integer `order`, preserving declaration order on ties; blocks/sections retain list
order. All copy is **plain escaped text**, including `custom_richtext`: no raw HTML
or executable Markdown. CTA/item URLs must be absolute local paths (`/contact`) or
HTTP(S) URLs without credentials, never protocol-relative or script URLs; blank CTA
URLs suppress links. Missing CTA URLs default to an enabled quote page, then contact.
Master gates `ENABLE_SERVICES`, `ENABLE_GALLERY`, `ENABLE_SCHEDULING` still apply;
gallery previews/navigation additionally require public gallery items. Disabled
manifest pages are hidden and unavailable. Unknown fields/types, duplicate page keys
or slugs, unsafe URLs, and oversized manifests are rejected.

Public routes include `/service-area` with `/directions` as an alias,
`/p/<slug>` for enabled custom pages, and `/request-quote` as an alias for
`/quote-request`. Review the selected preset's links and copy before publishing.

### Tenant routing (Waves 1-4)

Development and testing automatically provide a `default` tenant using `DATABASE_URL`
(the testing database in tests), limited to `localhost`, `127.0.0.1`, and `[::1]`.
Other hosts fail closed. Production requires an explicit tenant map; there is no
fallback to a customer database for unknown or disabled hosts.
`DATABASE_URL` remains required in production for the default extension/maintenance
binding; HTTP customer sessions never fall back to that database.

Set `TENANTS_JSON` in the environment, or supply an equivalent `TENANTS` mapping through
`create_app(..., config_overrides={...})` **before** extensions initialize:

```json
{
  "alpha": {
    "hosts": ["alpha.example.test"],
    "database_uri": "sqlite+pysqlite:///alpha.db",
    "enabled": true,
    "settings": {
      "BUSINESS_NAME": "Alpha Services",
      "BUSINESS_PHONE": "555-0101",
      "ENABLE_SCHEDULING": false,
      "CANONICAL_ORIGIN": "https://alpha.example.test"
    }
  },
  "beta": {
    "hosts": ["beta.example.test"],
    "database_uri": "sqlite+pysqlite:///beta.db",
    "enabled": true,
    "settings": {
      "BUSINESS_NAME": "Beta Works",
      "ENABLE_SCHEDULING": true,
      "CANONICAL_ORIGIN": "https://beta.example.test"
    }
  }
}
```

Use separate PostgreSQL database URLs in production, supplied through protected
configuration rather than committed files. Registry data is loaded outside
the customer session router; file changes reload before subsequent HTTP requests in
each worker. In-flight requests retain their original snapshot. Explicit tenant maps
disable the automatic local default. Host matching ignores ports and case, accepts a
trailing dot, and treats `www.` as an alias. Conflicting aliases fail at startup.
Only enable `TRUST_PROXY` behind the configured trusted proxy; forwarded host handling
runs before tenant selection. Configure nginx domains and certificates accordingly.

Customer ORM queries and SQL executed through `db.session` use the active tenant.
Each database pool defaults to two connections, no overflow, a 30-second checkout
timeout, pre-ping, and 30-minute recycling, per worker. In-memory SQLite uses its
single-connection static pool. Request teardown removes the session and rolls back
uncommitted work. Authentication and remember cookies contain tenant-qualified user
IDs; existing unqualified login sessions must sign in again.

Non-request database work with an explicit tenant map requires a fresh application
context:

```python
from app.tenancy import tenant_context

with app.app_context(), tenant_context("alpha") as tenant:
    # ORM operations here use alpha's database.
    ...
```

This selects ORM routing and tenant settings: `db.engine`, `db.create_all()`, and
unqualified extension operations do **not** automatically select that tenant.
For explicit engine work, use `app.extensions["tenancy"].engine_for(tenant)`.
CLI/migration operations select tenants explicitly as described below; there is no
automatic fleet-wide mutation.

### Tenant provisioning and operations (Wave 4)

### Super-Admin Fleet Control (T5.6 / Deploy Gate #17)

Set a strong `SUPERADMIN_PASSWORD`, `TENANT_REGISTRY_FILE=tenants.json`, and preferably
a dedicated `SUPERADMIN_HOST` such as `control.platform.test`. Serve it over TLS with
its own DNS/certificate and proxy host routing. The configured `SUPERADMIN_PATH`
(default `/platform/control`) is a standalone, server-rendered operator page: no
tenant DB binding, tenant navigation, or tenant-login authorization is used. Blank or
unset master passwords return 404, as do all non-permitted hosts when a control host
is set. Leaving the host blank deliberately permits the control path on any valid
hostname; use a dedicated host in production. A hostname setting alone does not
provision DNS, nginx server names, certificates, or firewall rules.

The page inventories all registered tenants, including disabled tenants, with schema
head status, row counts, redacted database details, upload bytes/files, palette ID,
business identity, effective public preset and feature flags. Preset/content settings
remain editable even when a tenant database is unavailable. Health is degraded for unavailable/incomplete
tenant databases or pending migrations. Inventory is synchronous/read-only; very large
fleets or upload trees can make refreshes slower. Disabled tenants remain available
for targeted maintenance but never serve customer requests.

Inline forms provision a dedicated database (SQLite by default; supply an existing,
independent PostgreSQL database in production), migrate to head, create storage, and
optionally create an admin and seed demo data. Admin email/password must be supplied
together or both omitted. Identity/domain/flag/preset/manifest edits and enable/disable actions write
the private registry atomically and reload workers on their next request. Move static
tenant definitions into the registry file before editing them here; static definitions
are inventoried and support maintenance, but their deployment-owned identity/status
cannot be overwritten from the dashboard. Changing domains clears stale canonical
origin overrides. PostgreSQL database creation and DNS/TLS remain infrastructure tasks.

Upgrade and backup actions target only the selected tenant. Backups use the same
checksummed database/upload/theme routine as the backup script, retain seven artifacts
per slug under the instance directory's platform-backups area, and display the created
artifact path. Continue scheduling backups/off-host copies and restore verification.
Demo reset is rendered/permitted only for `DEMO_TENANT=True` and requires the exact
slug confirmation; it preserves admin accounts while replacing demo business data.
Provisioning failures are not published, but migrations/storage creation are not a
distributed transaction: inspect and remove any orphan new-tenant artifacts before retrying.

Launch tenant admin uses a signed, 60-second, single-use token scoped to the selected
tenant and active admin account. It redirects only to a registered tenant host over
HTTPS, never an arbitrary canonical origin. Consumption is recorded atomically in a
separate platform SQLite ledger shared by workers in the instance directory. Multi-host
deployments must share this durable ledger (or replace it with a shared transactional
store). Tokens are rejected when replayed, expired, tampered with, used on another
tenant, or after master/signing-key rotation. The tenant admin shows a persistent
impersonation warning and CSRF-protected Exit Impersonation button. No master session
proof is carried into the tenant session. Keep cookies host-only and never share a
session cookie domain across tenants.

Master login has an independent `_superadmin_authenticated` HMAC session proof,
constant-time password verification, CSRF protection, and an always-on platform IP
limiter using `RATE_LIMIT_LOGIN_REQUESTS` / `RATE_LIMIT_LOGIN_WINDOW_SECONDS`. Like the
existing limiter, counters are process-local and reset on restart; add proxy-level
throttling/network access controls for a hard multi-worker limit. Raw forwarded IP
headers are ignored unless processed by the configured trusted proxy. Every action
records a structured `superadmin.<action>` event, target slug and outcome, without
passwords or handoff tokens. Configure proxy access logs to omit query strings on the
handoff endpoint so bearer tokens are not logged. Platform pages and handoff responses
are no-store/no-referrer; hide the control host behind VPN/allowlists where possible.

Verification: the superadmin regression suite exercises the fail-closed boundary,
CSRF/throttling, real provisioning/migrations, live registry changes, isolated backups
and demo resets, and durable handoff replay rejection.

### CLI tenant provisioning

Set `TENANT_REGISTRY_FILE=tenants.json` in `.env` to enable persistent provisioning.
Relative paths resolve beneath Flask's instance directory. A missing/empty registry
starts with no customer hosts and fails closed until tenants are provisioned; this mode
disables the automatic local default. The file uses the same JSON mapping shown above.
It may supplement a static `TENANTS_JSON` map, but duplicate slugs/domains are rejected.
Keep registry/database credentials private, out of Git, and restrict filesystem access.

```powershell
python -m flask --app run.py tenant create alpha --domain alpha.example.test --admin-email admin@alpha.example.test
python -m flask --app run.py tenant create beta --domain beta.example.test
python -m flask --app run.py create-admin --tenant beta --email admin@beta.example.test
python -m flask --app run.py tenant list
python -m flask --app run.py tenant upgrade alpha
# Equivalent Alembic selection, including current/migrate/downgrade operations:
python -m flask --app run.py db -x tenant=alpha upgrade
```

Passwords are prompted invisibly. `--admin-password` (provisioning) or `--password`
(admin creation) is available for automation, but avoid secrets in shell history.
`create-admin` and `create-dev-admin` both accept `--tenant`; omitting it only works with
the automatic default tenant. `seed-demo --tenant <slug>` adds synthetic services,
customers, requests across statuses, quote records, appointments, and a labeled gallery
illustration. Re-running does not duplicate the demo. Existing business data is refused
unless you use the guarded reset workflow; admin accounts are always preserved.

Mark only disposable tenants with `"DEMO_TENANT": true` in their settings. Reset one with
`flask seed-demo --tenant demo --reset`; this deletes its business records and referenced
upload files, then reseeds it. It never resets another tenant, changes themes/settings,
or sends notification emails. Schedule that command against a dedicated demo tenant;
do not give prospects administrative access to real customer tenants.
Non-demo resets require **both** `--force --confirm <exact slug>` and are destructive.
Take a tenant backup first. The separate UI sweep seeder remains disposable test tooling.

`tenant create` accepts repeated `--domain`, `--demo` (disposable with email disabled),
an optional `--settings` JSON object, `--preset` (one of the three public presets), and
`--database-uri`. Without a URI it creates
`instance/tenants/<slug>/tenant.sqlite3`; in-memory SQLite cannot be provisioned.
For production, pre-create a dedicated PostgreSQL database and supply its SQLAlchemy
URI through `--database-uri`; this command migrates the database, not PostgreSQL roles
or server-level databases. It runs Alembic through the real migration head, creates all
three upload-category directories, optionally seeds an admin, then atomically publishes
the record. Known database reuse, duplicate aliases, invalid settings, and concurrent
registry writes are rejected. Failed migrations do not publish a tenant; inspect any
partially initialized SQLite database before retrying.

Registry file changes reload before subsequent HTTP requests in each worker.
Configure DNS, nginx hosts, TLS, and tenant settings before exposing the
new domain. Keep the instance path stable across CLI commands and server workers.

```powershell
python scripts\backup.py --tenant alpha --out backups --keep 14
python scripts\restore_check.py --tenant alpha --root backups
# Or verify a specific directory returned by backup.py:
python scripts\restore_check.py --tenant alpha backups\alpha\<timestamp>
```

Backups live beneath `<out>/<slug>/<UTC timestamp>` and include a PostgreSQL custom dump
or native SQLite snapshot, a tenant-only upload archive, optional `theme.json`, checksums,
row counts, migration revision, and tenant identity. Retention is scoped to that tenant's
completed backups. PostgreSQL dumps and counts share an exported snapshot; pause writes
on the selected tenant while capturing files so database/media/theme state is consistent.
The automatic default retains the legacy backup layout and needs no `--tenant` flag.

Restore checks reject mismatched tenants/checksums/unsafe archive paths before restoring.
They verify media/theme in temporary storage and database counts/revision in a temporary
SQLite database or unique PostgreSQL scratch schema. They **never restore over live
tenant data**. `--keep` retains successfully verified scratch data for inspection.
Only use trusted application backups; PostgreSQL support assumes the application's
`public` schema and requires `pg_dump`, `pg_restore`, and `psql` (configure `PG_BIN`).
Back up the protected registry file separately; credential rotation and an actual
production cutover remain explicit operator actions, not automated by restore checks.

### Tenant settings and appearance (Wave 2)

Each tenant's optional `settings` mapping overrides application defaults. Read settings
through `tenant_config(key, default=None)` or the read-only `current_tenant_settings()`
mapping from `app.tenancy`; neither changes `app.config` nor the process environment.
Nested logo/social mappings are read-only too. Settings are snapshotted per request;
file-backed registry changes reload before the next request. JSON flags must be booleans, not strings;
invalid types, ranges, unsupported settings, and non-HTTPS canonical origins fail startup.

Supported settings include:

- Business name/contact/address/tagline/service area; `BUSINESS_NAME` and `COMPANY_NAME`
  are aliases, as are `STAFF_COMPENSATION_CURRENCY` and `COMPENSATION_CURRENCY`.
- All module `ENABLE_*` flags; `SITE_LOGO_PATH`/`SITE_LOGO_ALT` or `SITE_LOGO`;
  `SOCIAL_LINKS`, `SOCIAL_<PLATFORM>_ENABLED`/`_URL`, and `SOCIAL_LINKS_PREVIEW`.
  Social entries merge by platform; flat platform settings take precedence.
- `EMAIL_ENABLED`, `ADMIN_NOTIFICATION_EMAIL`, `DEFAULT_FROM_EMAIL`, `EMAIL_FROM_NAME`,
  `EMAIL_REPLY_TO`, and optional `SMTP_*` overrides. Overriding business identity also
  supplies tenant sender-name/address defaults unless explicitly overridden.
- `RECAPTCHA_*`, `SITE_THEME`, and `RATE_LIMIT_*`.
- `SITE_PRESET` and `PUBLIC_PAGES_CONFIG` (public layout/content; see schema above).

`CANONICAL_ORIGIN` is an HTTPS origin without a path, credentials, query, or fragment.
For explicit tenants it defaults to HTTPS on the first registered host, never the incoming
request host. Notifications use it both during requests and within `tenant_context` jobs.
The automatic local/test tenant preserves legacy development URLs when no origin is set.

Explicit tenants persist appearance in `instance/tenants/<slug>/theme.json`; they never
read the legacy shared theme file. The automatic local/test tenant retains
`instance/theme.json` for compatibility. Rate-limit counters use
`tenant_slug:bucket:client_ip`; they remain in-memory and per worker, not a distributed
quota.

### Tenant uploads and media (Wave 3)

Explicit tenants store files beneath `instance/tenants/<slug>/uploads`, separately from
the shared static tree. Uploads, deletion, directory cleanup, and failure rollback all
resolve through the active tenant's root, including outside requests within
`tenant_context`. Tenant roots must not redirect through symlinks; resolved file paths
must remain inside their permitted tenant/category boundaries.

Database keys remain relative and unchanged in shape:
`uploads/quote_requests/<id>/<filename>`, `uploads/customers/<id>/<filename>`, and
`uploads/gallery/<filename>`. They contain neither absolute filesystem paths nor tenant
directory prefixes. Equal record IDs and filenames across tenants remain isolated.

- Private request/customer photos use the authenticated `/admin/media/<path>` endpoint
  with private caching and noindex headers.
- Explicit tenant gallery images use `/media/gallery/<filename>`, generated through
  `media_url`. This public endpoint resolves only gallery files and requires the active
  tenant's `ENABLE_GALLERY` flag.
- Explicit tenants cannot access shared `/static/uploads/` URLs. The nginx deployment
  configuration blocks the entire legacy static-upload prefix; shared code and branding
  assets remain served from static storage.

The automatic local/test default tenant keeps `UPLOAD_FOLDER` and legacy public static
gallery URLs for single-tenant compatibility. This fallback does not apply to explicit
tenant maps, even when they contain only one tenant.

Existing files are **not automatically moved**. Before enabling an explicit tenant map,
manually place each tenant's files under its instance upload root, preserving the
`quote_requests`, `customers`, and `gallery` subdirectories and database keys. Back up
each tenant database together with its instance directory (including its theme file).
Tenant provisioning and targeted backup/restore verification are described above.

## Testing and quality gates

```powershell
python -m pytest -q
python scripts\ui_sweep.py          # every route, 390/768/1440, screenshots + report
```

The sweep boots its own seeded SQLite database, logs in through the real form, and reports
horizontal overflow, WCAG contrast failures, broken images, unlabeled controls, JS errors
and failed requests — with a full-page screenshot per route per width. `--matrix` sweeps
the feature-flag presets. CI runs both jobs on every push.

Runtime packages (including `openpyxl` for spreadsheet imports) are pinned in
`requirements.txt`; `requirements-dev.txt` includes runtime packages plus pytest and
Playwright. CI uses the same dev manifest. Run `python -m pip check` after installation.

### Monitoring and exception reporting

`GET /healthz` returns exactly `{"status":"ok"}` with 200, even without a registered
tenant host. It performs no database query and is exempt from rate limiting. This is a
platform responsiveness check, not proof that every tenant database is ready.
`GET /healthz?db=1` requires a registered, enabled host and executes a small query only
against that tenant; unknown hosts fail closed and database failures return JSON 503.

Production requests emit JSON logs to the existing application log stream with level,
timestamp, request ID, endpoint/status, and tenant scope. Responses include
`X-Request-ID`; request bodies/cookies and exception values are not added to monitoring
events. Configure retention and restricted access in your server log collector.

Optionally set `ERROR_WEBHOOK_URL` to a trusted HTTPS endpoint. Unset means no outbound
reporting. Unhandled exceptions send only exception class, request ID, and tenant slug,
not names, form data, credentials, paths, or stack traces. Delivery has a short timeout;
failure is logged and `flask test-error-reporting` exits unsuccessfully. That CLI command
sends a synthetic event when enabled, or explains that reporting is disabled.
No public endpoint deliberately triggers exceptions. Configure uptime alerts and verify
the webhook with your provider during deployment.

Privacy/terms pages interpolate each tenant's identity and describe the implemented
data flows. Owners should review them for their jurisdiction, retention practices, and
actual service contracts before publishing; the supplied copy is not legal advice.
See [the owner guide](docs/OWNER-GUIDE.md) for day-to-day operation.

## Operating it

```powershell
python -m flask --app run.py tenant upgrade alpha
python scripts\backup.py --tenant alpha --keep 14
python scripts\restore_check.py --tenant alpha
```

Repeat explicitly for each tenant; these commands never enumerate and mutate a fleet.
The legacy `rehearse_migrations.py --smoke` helper is for default single-tenant setups,
not explicit registries. Before production rollout, run the full test suite and verify
tenant migrations/backups on the deployment's PostgreSQL version.

Deployment runbook for a Linux host: [`deploy/README.md`](deploy/README.md).
Per-deployment checklist: [`DEPLOYMENT_CHECKLIST.md`](DEPLOYMENT_CHECKLIST.md).
Page-by-page UI finish line: [`PAGE-INVENTORY.md`](PAGE-INVENTORY.md).
Architecture notes: [`PROJECT.md`](PROJECT.md).

## Security notes

- **Private uploads.** Explicit tenants have separate instance upload roots; the
  automatic local/test tenant retains the legacy upload folder. Shared static uploads
  are blocked for explicit tenants. Private files use the authenticated
  `/admin/media/<path>` route with containment checks, `Cache-Control: private` and
  `X-Robots-Tag: noindex`. Tenant gallery media is public only when enabled.
- **Sessions.** Deactivated accounts lose access on their next request; Flask-Login only
  checks `is_active` at login time, so the user loader enforces it every time.
- **Rate limiting.** In-app fixed windows for anonymous forms and login. Counters are per
  worker process, so the effective limit is roughly `workers × limit` — a spam speed bump
  beside reCAPTCHA, not a security boundary.
- **Merge safety.** Merging duplicate customers moves every customer-owned record
  (photos, recurring plans, appointments, requests, fields, notes, addresses) before the
  duplicate is deleted.

## Project structure

```text
app/
  __init__.py         # factory, error handlers, upload guard, rate limiting, ProxyFix
  cli.py              # admin bootstrap commands
  config.py           # environment-aware settings
  data/themes.json    # 100-palette theme library
  admin/ auth/ main/  # blueprints
  forms/ models/      # WTForms and SQLAlchemy models
  services/           # email, media access, rate limiting, themes, imports, business logic
  static/js/          # page and component JavaScript (extracted from templates)
  static/css/app.css  # single stylesheet, token-driven
  templates/          # Jinja templates
deploy/               # gunicorn, systemd, nginx, first-boot runbook
migrations/           # Alembic
scripts/              # ui_sweep, rehearse_migrations, backup, restore_check
tests/                # 207 tests
```

## Not included

React/SPA frontend, JSON API layer, multi-tenancy (one deployment per customer), payments,
customer portal, SMS, SaaS billing.

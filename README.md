# Quote Request System

A reusable Flask starter for service businesses: a public marketing site, a quote/work
request intake, and an internal operations dashboard — with the optional parts switchable
per customer from a single config file.

Server-rendered HTML, no SPA, no build step. Multi-tenancy supports host-selected
databases, tenant-bound authentication, and tenant-specific branding, feature flags,
integrations, themes, rate-limit buckets, and partitioned upload/media storage in one
application instance. Tenant provisioning and fleet operations remain manual.

## What it does

**Public site**

- Landing page, services, gallery, about, contact, FAQ, privacy, terms
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

Flags are enforced server-side, not just in the navigation: a disabled module's routes
return 404 (admin) or redirect (public), and a crafted POST creates nothing.

## Tech stack

Flask 3.1 · PostgreSQL (SQLite for tests) · SQLAlchemy + Flask-Migrate · Flask-Login ·
Flask-WTF · Jinja templates · one stylesheet · plain JavaScript in `app/static/js/` ·
pytest · GitHub Actions · gunicorn + nginx in production.

## Quick start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# optional: only needed to run the UI sweep
python -m pip install playwright

copy .env.example .env      # then edit: SECRET_KEY, DATABASE_URL, BUSINESS_*
python -m flask --app run.py db upgrade
python -m flask --app run.py create-admin
python -m flask --app run.py run
```

Then open <http://127.0.0.1:5000/>. The admin lives at `/admin`.

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

Everything lives in `.env` (see `.env.example` for the full annotated list). The ones that
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

### Tenant routing (Waves 1-3)

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
configuration rather than committed files. Registry data is loaded at startup, outside
the customer session router; restart workers after changing it. Explicit tenant maps
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
the existing migration commands do **not** automatically select that tenant.
For explicit engine work, use `app.extensions["tenancy"].engine_for(tenant)`.
Provision and migrate each tenant database explicitly; automatic fleet migrations and
tenant-aware CLI command options are deferred to Wave 4. Existing backup/restore scripts
must not be assumed to cover every tenant database and instance storage directory.

### Tenant settings and appearance (Wave 2)

Each tenant's optional `settings` mapping overrides application defaults. Read settings
through `tenant_config(key, default=None)` or the read-only `current_tenant_settings()`
mapping from `app.tenancy`; neither changes `app.config` nor the process environment.
Nested logo/social mappings are read-only too. Settings are snapshotted at startup, so
restart workers after changing the registry. JSON flags must be booleans, not strings;
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
Provisioning, migration, and fleet backup/restore CLI changes remain deferred to Wave 4.

## Testing and quality gates

```powershell
python -m pytest -q
python scripts\ui_sweep.py          # every route, 390/768/1440, screenshots + report
```

The sweep boots its own seeded SQLite database, logs in through the real form, and reports
horizontal overflow, WCAG contrast failures, broken images, unlabeled controls, JS errors
and failed requests — with a full-page screenshot per route per width. `--matrix` sweeps
the feature-flag presets. CI runs both jobs on every push.

## Operating it

```powershell
python scripts\rehearse_migrations.py --smoke   # prove migrations on Postgres before deploying
python scripts\backup.py --keep 14              # dump + uploads + manifest
python scripts\restore_check.py                 # restore into a scratch schema and verify
```

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

# Quote Request System

A reusable Flask starter for service businesses: a public marketing site, a quote/work
request intake, and an internal operations dashboard — with the optional parts switchable
per customer from a single config file.

Server-rendered HTML, no SPA, no build step, one database. Deployed as a template: each
customer gets their own copy, their own database, their own branding and feature set.

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

Every optional module is a feature flag, so one deployment only carries what it sells.

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
| `SECRET_KEY` | Unique per customer. Never reuse the dev key. |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` |
| `ENABLE_*` | Which modules this deployment includes |
| `RATE_LIMIT_*` | Anonymous form and login throttling |
| `EMAIL_ENABLED`, `SMTP_*` | Transactional email (Brevo-compatible); off by default |
| `RECAPTCHA_*` | Spam protection on the public forms |
| `TRUST_PROXY` | Set true only behind nginx, so client IPs and scheme are correct |
| `SITE_THEME` | Deploy-time default palette; customers can change it later in admin |

## Testing and quality gates

```powershell
python -m pytest -q                 # 207 tests
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

- **Private uploads.** Request and customer photos live under `app/static/uploads/` but
  the static route 404s those prefixes; they are served by an authenticated
  `/admin/media/<path>` route with traversal checks, `Cache-Control: private` and
  `X-Robots-Tag: noindex`. Gallery images stay public on purpose.
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

# Project Overview

Quote Requests is a server-rendered Flask application for service businesses that need a public website, a quote-intake workflow, and a lightweight internal operations dashboard. The original core flow is public quote submission into an internal review queue. The current codebase has expanded that into customer records, scheduling, staff assignment, recurring work, service catalog management, gallery/content management, and import utilities.

Primary users:

- Public visitors requesting quotes or scheduled work
- Internal staff/admin users managing requests, customers, appointments, recurring work, gallery content, services, and staff

This is not a SPA and not an API-first system. The product is primarily server-rendered HTML with small amounts of inline JavaScript for progressive enhancement.

# Architecture

## High-Level Shape

- Runtime: Flask application factory in `app/__init__.py`
- Entry points: `run.py` for local development, `wsgi.py` for production WSGI
- Presentation: Jinja templates in `app/templates/`
- Styling: single stylesheet in `app/static/css/app.css`
- Persistence: Flask-SQLAlchemy models backed by PostgreSQL in development/production and SQLite in tests
- Schema migrations: Flask-Migrate/Alembic in `migrations/`
- Auth: Flask-Login session authentication
- Forms/validation: Flask-WTF and WTForms
- Tests: pytest with database-per-test fixtures

## Frontend

- Framework: none; server-rendered Jinja templates
- Routing: Flask blueprints render HTML directly
- State management: request/response state, form POSTs, query params, and server-side persistence
- Layout: `base.html` is the global shell; `site_base.html` wraps brochure/public pages
- Styling system: custom CSS variables and component classes in `app/static/css/app.css`
- JavaScript: lightweight inline scripts for confirm dialogs and some admin UX; no frontend build pipeline

Frontend structure is split between:

- Public brochure pages under `app/templates/main/`
- Admin dashboard/workflow pages under `app/templates/admin/`
- Shared header/footer partials under `app/templates/partials/`

## Backend

- Framework: Flask 3.1
- App factory: `create_app()` in `app/__init__.py`
- Blueprints:
  - `main`: public brochure, quote request, schedule work, gallery, legal/info pages
  - `auth`: login/logout routes and safe `next` handling
  - `admin`: dashboard and all internal operations workflows
- Controllers: route handlers in each blueprint's `routes.py`
- Services: business logic lives mostly in `app/services/`
- Middleware/extensions: SQLAlchemy, Migrate, LoginManager, CSRFProtect initialized in `app/extensions.py`

The codebase generally keeps route handlers thin and pushes workflow/data rules into service modules. The main exception is `app/admin/routes.py`, which is a large orchestration file that still contains substantial page-assembly logic.

## Database

- ORM: Flask-SQLAlchemy / SQLAlchemy 2.x style via the Flask extension
- Migrations: Alembic revisions under `migrations/versions/`

Primary tables/entities:

- `users`: admin login accounts
- `quote_requests`: public intake records for both quote requests and work requests
- `request_photos`: uploaded quote request images
- `request_notes`: internal notes on requests
- `request_quotes`: quote tracking records/decisions
- `customers`: durable customer records
- `customer_fields`: additional contact/identity fields linked to customers
- `customer_addresses`: addresses and billing flag
- `customer_notes`: internal customer notes
- `customer_photos`: customer-scoped image uploads
- `appointments`: scheduled/requested/rescheduled work items
- `staff_members`: internal staff/crew records
- `staff_availabilities`: weekly availability windows
- `appointment_staff_assignments`: staff-to-appointment assignments
- `service_options`: configurable service catalog
- `gallery_items`: public gallery content items
- `recurring_works`: recurring service plans with recurrence config

Important relationships:

- `QuoteRequest` belongs optionally to `Customer`
- `QuoteRequest` has many `RequestPhoto`, `RequestNote`, `RequestQuote`, and `Appointment`
- `QuoteRequest` has many-to-many `ServiceOption`
- `Appointment` belongs optionally to `Customer`, `QuoteRequest`, and `RecurringWork`
- `Appointment` has many-to-many `ServiceOption`
- `Appointment` has many staff assignments through `AppointmentStaffAssignment`
- `Customer` has many `QuoteRequest`, `Appointment`, `RecurringWork`, `CustomerField`, `CustomerAddress`, `CustomerPhoto`, and `CustomerNote`
- `StaffMember` has many `StaffAvailability` and many-to-many `ServiceOption`
- `GalleryItem` optionally links to one `ServiceOption`

## Authentication, Roles, Permissions

- Login flow is session-based via Flask-Login
- Canonical admin entry route is `/admin`
- Legacy login GETs redirect from `/auth/login`, `/login`, and `/dashboard/login`
- Passwords are hashed with Werkzeug password hashing
- Logout is POST-only
- There is no JWT layer
- There is no role hierarchy or granular permission model in the current schema

Practical implication: the system currently behaves as a single-role authenticated admin application.

## Infrastructure and Integrations

- Environment loading: repo-root `.env` via `python-dotenv`
- Database: PostgreSQL for dev/prod, SQLite for tests
- Email: stub/log-only hooks in `app/services/email_hooks.py`
- File uploads: local filesystem storage under `app/static/uploads/`
- Image validation: extension, MIME check, signature/Pillow verification
- Spam protection: optional reCAPTCHA v3 integration
- Imports: CSV/XLSX customer/staff import workflow using `openpyxl`
- Background jobs: none
- Scheduled tasks: none external; recurring work sync happens during request handling in admin flows
- Logging: mostly `current_app.logger` in service modules
- Error handling: form errors, flashed messages, `BadRequest`/`NotFound`, explicit CSRF and large-upload handlers

# Technology Stack

- Python 3
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-WTF
- PostgreSQL
- SQLAlchemy
- Alembic
- Jinja2
- WTForms
- Pillow
- openpyxl
- python-dotenv
- pytest
- Docker Compose for optional local Postgres

# Folder Responsibilities

## Root

- `run.py`: local Flask entrypoint
- `wsgi.py`: production WSGI entrypoint
- `README.md`: primary setup and usage guide
- `PROJECT.md`: onboarding/reference document
- `DEPLOYMENT_CHECKLIST.md`: customer deployment checklist
- `requirements.txt`: Python dependency pins/ranges
- `docker-compose.yml`: optional PostgreSQL container for local development
- `.env.example`: environment template
- `restart_flask.ps1`, `scripts/start_flask_server.ps1`: local Windows helper scripts

## Application Code

- `app/__init__.py`: app factory, blueprint registration, context processors, error handlers, runtime directory setup
- `app/config.py`: config classes, feature flags, branding, social link config, env parsing
- `app/extensions.py`: Flask extension singletons
- `app/cli.py`: `create-admin` and `create-dev-admin` commands
- `app/date_ranges.py`: date range preset helpers used by scheduling/calendar views

## Blueprints

- `app/main/`: public site routes and quote/schedule intake
- `app/auth/`: login/logout behavior
- `app/admin/`: internal dashboard and operations workflows

## Forms

- `app/forms/quote_request.py`: public intake form
- `app/forms/auth.py`: login form
- `app/forms/admin.py`: admin CRUD/workflow forms
- `app/forms/time_selects.py`: shared time-select helper mixin

Pattern: forms carry field definitions plus cross-field validation; route handlers then call service functions with validated data.

## Models

- `app/models/`: SQLAlchemy entity definitions grouped by domain

Pattern: models expose lightweight computed properties and relationship definitions; domain mutations mostly happen in services instead of model methods.

## Services

- `app/services/quotes.py`: create public quote/work requests and optional linked appointments
- `app/services/auth.py`: credential verification
- `app/services/uploads.py`: filesystem upload handling and image validation
- `app/services/recaptcha.py`: reCAPTCHA verification
- `app/services/service_catalog.py`: service feature gating and service CRUD/order logic
- `app/services/gallery_catalog.py`: gallery feature gating and gallery CRUD/order logic
- `app/services/import_workflows.py`: CSV/XLSX preview/commit workflows for customer/staff imports
- `app/services/email_hooks.py`: email hook stubs/logging
- `app/services/admin_requests.py`: main business workflow module for requests, customers, appointments, staff, recurring work, quotes, and linking logic

Pattern: service modules use `db.session` directly, raise `BadRequest`/`NotFound` for route-level handling, and commit at the service boundary.

## Templates and Assets

- `app/templates/base.html`: shared shell for both public and admin surfaces
- `app/templates/site_base.html`: public-site shell extension
- `app/templates/partials/`: reusable public header/footer partials
- `app/templates/main/`: brochure/public pages
- `app/templates/admin/`: admin pages and a few reusable admin fragments/scripts
- `app/static/css/app.css`: single global stylesheet
- `app/static/assets/`: image assets/icons/logo
- `app/static/uploads/`: local uploaded media storage

## Database and Tests

- `migrations/`: Alembic environment and revision history
- `tests/`: pytest suite covering public pages, request workflow, services, gallery, appointments, staff, recurring work, and regression flows

Test pattern: integration-style Flask client tests using a temporary SQLite database seeded with default service options in `tests/conftest.py`.

# Development Workflow

## Environment Setup

1. Create a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Copy `.env.example` to `.env` and set local values.
4. Start PostgreSQL locally or via `docker-compose.yml`.
5. Apply migrations.
6. Run the Flask dev server.

## Verified Commands

Dependency install:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run migrations:

```powershell
.venv\Scripts\python.exe -m flask --app run.py db upgrade
```

Run the dev server:

```powershell
.venv\Scripts\python.exe -m flask --app run.py run --debug
```

Create an admin user:

```powershell
.venv\Scripts\python.exe -m flask --app run.py create-admin
```

Create a development admin:

```powershell
.venv\Scripts\python.exe -m flask --app run.py create-dev-admin
```

Run tests:

```powershell
.venv\Scripts\python.exe -m pytest
```

## Build Verification Results

What was verified during onboarding:

- Dev server started successfully on `http://127.0.0.1:5001`
- Home page returned HTTP 200
- Full test suite executed

What failed:

- `pip install -r requirements.txt` failed while trying to satisfy `Pillow>=10,<11`
- Full pytest run reported existing failing tests on the current branch

Why install failed:

- The checked environment uses Python 3.14.2
- The virtualenv already has Pillow 12.2.0 installed
- The repo requires `Pillow<11.0`, so pip attempted to downgrade to Pillow 10.4.0
- On this Windows/Python 3.14 environment, pip fell back to a source build and failed because the required zlib/native build prerequisites were not present

Practical fix options:

- Use a Python version that matches the pinned dependency range more comfortably, such as 3.12 or 3.13
- Or update the repo's Pillow pin after validating compatibility, then reinstall

Pytest result:

- 158 tests collected
- 149 passed
- 9 failed

Failing areas observed:

- recurring work customer-context creation/detail flows
- staff list workflow expectations
- workflow regression expectations around appointment/customer detail content

There is no lint command configured in the repository today. There is also no frontend or packaging build step; this is a server-rendered Flask app without a separate asset pipeline.

# Testing Instructions

- Main command: `.venv\Scripts\python.exe -m pytest`
- Tests use temporary SQLite databases, not the Postgres development database
- `tests/conftest.py` seeds default `ServiceOption` rows for consistent fixtures
- Feature-flagged tests often explicitly enable the relevant subsystem in `app.config`

The test suite is integration-heavy rather than unit-heavy. It primarily validates route behavior, rendered HTML, redirects, feature flags, and workflow persistence.

# Deployment Overview

- Production entrypoint is `wsgi.py`
- Production requires at minimum `DATABASE_URL` and a non-default `SECRET_KEY`
- `DEPLOYMENT_CHECKLIST.md` documents per-customer deployment expectations
- Branding, social links, feature flags, and reCAPTCHA settings are environment-driven
- Session cookies are hardened in production config with secure flags

This repo appears intended for customer-specific deployments rather than one shared multi-tenant SaaS runtime.

# Coding Conventions

Observed conventions in the current codebase:

- Keep routes reasonably thin and delegate persistence/business rules to service modules
- Use Flask blueprints for domain separation
- Use Flask-WTF/WTForms for all HTML form handling
- Perform cross-field validation inside form `validate()` overrides
- Use `BadRequest` and `NotFound` in services for recoverable workflow errors
- Commit database changes at the service-function boundary
- Use computed model properties for display-oriented or derived state
- Prefer feature flags in config/context processors over branching templates by deployment
- Keep templates server-rendered and feature-flag aware
- Use snake_case for Python names and descriptive class/function names
- Use integration tests with Flask test client for workflow coverage

Architectural constraints to respect in future work:

- Extend the existing blueprint/form/service/model pattern rather than introducing a new application layer
- Avoid introducing a JS framework or API layer unless explicitly required
- Prefer adding to `app/services/admin_requests.py` only when the change truly belongs to an existing workflow, otherwise consider a focused sibling service module

# Environment Variables

Core runtime:

- `FLASK_APP`
- `FLASK_ENV`
- `SECRET_KEY`
- `DATABASE_URL`
- `TEST_DATABASE_URL`

Feature flags:

- `ENABLE_GALLERY`
- `ENABLE_SERVICES`
- `ENABLE_SCHEDULING`
- `ENABLE_STAFF_MANAGEMENT`
- `ENABLE_CUSTOMER_RECORDS`
- `ENABLE_CALENDAR`
- `ENABLE_RECURRING_WORK`

Branding/business info:

- `BUSINESS_NAME`
- `COMPANY_NAME` (legacy alias)
- `TAGLINE`
- `BUSINESS_PHONE`
- `BUSINESS_EMAIL`
- `SERVICE_AREA`
- `BUSINESS_ADDRESS`
- `SITE_LOGO_PATH`
- `SITE_LOGO_ALT`
- `BUSINESS_SERVICES`
- `STAFF_COMPENSATION_CURRENCY`

Email:

- `ADMIN_NOTIFICATION_EMAIL`
- `DEFAULT_FROM_EMAIL`

Spam protection:

- `RECAPTCHA_ENABLED`
- `RECAPTCHA_SITE_KEY`
- `RECAPTCHA_SECRET_KEY`
- `RECAPTCHA_MIN_SCORE`
- `RECAPTCHA_VERIFY_URL`

Social links:

- `SOCIAL_LINKS_PREVIEW`
- `SOCIAL_<PLATFORM>_ENABLED`
- `SOCIAL_<PLATFORM>_URL`

Platforms currently wired in config include Facebook, Instagram, LinkedIn, YouTube, X, TikTok, Pinterest, WhatsApp, Telegram, Skype, Snapchat, Spotify, Reddit, and Google Business.

# Important Files

- `app/__init__.py`: app bootstrap and cross-cutting runtime behavior
- `app/config.py`: environment model and feature flags
- `app/admin/routes.py`: central internal workflow controller surface
- `app/services/admin_requests.py`: largest business-rules module in the system
- `app/services/quotes.py`: public intake persistence path
- `app/services/uploads.py`: upload safety and filesystem handling
- `app/forms/admin.py`: admin-side workflow forms and validation
- `app/models/quote_request.py`: request, appointment, service, and quote entities
- `app/models/customer.py`: customer and recurring work entities
- `tests/conftest.py`: test app/db setup and default service seeding
- `DEPLOYMENT_CHECKLIST.md`: production/customer deployment notes

# Known Technical Debt

## Critical

- The repo currently has failing regression tests in recurring work, staff list, and workflow contract coverage. This means the branch is not in a fully green state.
- Dependency constraints are not aligned with the verified local interpreter: `Pillow<11` conflicts with the current Python 3.14-based environment, making a clean install unreliable.

## Important

- `app/admin/routes.py` is very large and acts as a controller hub for many subsystems, which increases change risk and onboarding cost.
- `app/services/admin_requests.py` is a very large multi-domain service module handling customers, appointments, staff, recurring work, notes, quotes, and sync logic. It is a concentration point for future coupling.
- There is no granular role/permission system; any authenticated user is effectively an admin.
- There is no configured linting/type-checking/formatting pipeline in the repo, which lowers automated guardrails.
- Recurring work synchronization occurs during request handling in admin views/routes, which can increase request cost and make side effects less obvious.

## Future Improvement

- Root-level temporary/debug artifacts are present (`tmp_*.html`, `tmp_check_live_quote.py`, log files). These should be treated as disposable local artifacts, not long-term project documentation.
- Email hooks are currently logging stubs rather than concrete outbound integrations.
- The public/admin UI relies on a single large stylesheet, which may become harder to evolve as features continue to grow.
- No TODO/FIXME/HACK comments were found in `app/`, so debt is mostly structural rather than explicitly annotated.

# Future Roadmap Observations

No formal roadmap file is present, but the migration history and current feature flags show the product has been expanding in this direction:

- quote intake to broader work-request scheduling
- request records to durable customer CRM-lite records
- single appointments to recurring work automation
- simple service selection to configurable service catalog
- internal workflow to brochure-site content management
- single-user admin to richer staff planning and availability workflows

If that direction continues, the most likely pressure points will be permissions, controller/service size, background processing for sync/import work, and stronger validation/tooling around releases.
# Quote Request System

## What This App Does

Quote Request System is a reusable Flask starter for service businesses that need a public quote request form and a lightweight internal admin workflow.

Version 1 is server-rendered and intentionally simple:

- public quote request form
- thank-you page after submission
- optional image uploads
- admin login/logout
- dashboard listing quote requests
- request detail page
- status updates
- internal notes
- email notification hooks for later integration

The goal is to provide a clean base you can reuse across service businesses without rebuilding the same workflow from scratch.

## Tech Stack

- Flask
- PostgreSQL
- SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-WTF
- Jinja templates
- Server-rendered HTML/CSS
- Pytest for test coverage

## Project Structure

```text
app/
  __init__.py          # application factory and bootstrap
  cli.py               # CLI commands for admin user creation
  config.py            # environment-aware settings
  extensions.py        # db, login manager, csrf, migrate
  admin/               # admin routes
  auth/                # login/logout routes
  forms/               # WTForms classes
  main/                # public routes
  models/              # SQLAlchemy models
  services/            # business logic and integrations
  static/              # CSS and uploaded files
  templates/           # Jinja templates
migrations/            # Alembic migration files
tests/                 # focused application tests
run.py                 # local Flask entrypoint
wsgi.py                # production WSGI entrypoint
docker-compose.yml     # optional local PostgreSQL container
requirements.txt
README.md
```

## Environment Variables

Copy [.env.example](c:/xampp/htdocs/quoterequests/.env.example) to `.env` and update as needed.

Supported variables:

- `FLASK_APP`: Flask entrypoint. Default: `run.py`
- `FLASK_ENV`: Flask environment. Default: `development`
- `SECRET_KEY`: Flask secret key. Required for real environments.
- `DATABASE_URL`: PostgreSQL connection string.
- `ADMIN_NOTIFICATION_EMAIL`: target email for admin notification hooks.
- `DEFAULT_FROM_EMAIL`: default sender for future email integration.
- `COMPANY_NAME`: brand name shown in the UI.

Example:

```env
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=change-me
DATABASE_URL=postgresql+psycopg://quote_requests:quote_requests@localhost:5432/quote_requests
ADMIN_NOTIFICATION_EMAIL=admin@example.com
DEFAULT_FROM_EMAIL=noreply@example.com
COMPANY_NAME=Service Company
```

## Local Setup

### 1. Create and activate a virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Configure environment variables

For a quick local shell session in PowerShell:

```powershell
$env:FLASK_APP = "run.py"
$env:FLASK_ENV = "development"
$env:SECRET_KEY = "dev-secret-key"
$env:DATABASE_URL = "postgresql+psycopg://quote_requests:quote_requests@localhost:5432/quote_requests"
```

If you prefer, store these in a local `.env` file and load them through your shell or editor workflow.

## Database Setup

Development is PostgreSQL-first. Tests use SQLite separately for speed and isolation.

### Option A: Native PostgreSQL

Create the role and database manually:

```sql
CREATE USER quote_requests WITH PASSWORD 'quote_requests';
CREATE DATABASE quote_requests OWNER quote_requests;
```

### Option B: Docker Compose

Use [docker-compose.yml](c:/xampp/htdocs/quoterequests/docker-compose.yml):

```powershell
docker-compose up -d
```

This starts PostgreSQL with:

- database: `quote_requests`
- user: `quote_requests`
- password: `quote_requests`
- host: `localhost`
- port: `5432`

## Migration Commands

Apply migrations:

```powershell
python -m flask --app run.py db upgrade
```

Create a new migration after schema changes:

```powershell
python -m flask --app run.py db revision -m "describe change"
```

Show current migration head:

```powershell
python -m flask --app run.py db heads
```

## How To Run The App

After PostgreSQL is running and migrations are applied:

```powershell
python -m flask --app run.py run
```

The local development server will be available at:

- `http://127.0.0.1:5000/quote-request`
- `http://127.0.0.1:5000/auth/login`

## How To Create An Admin User

Interactive admin creation:

```powershell
python -m flask --app run.py create-admin
```

Quick local development admin with defaults:

```powershell
python -m flask --app run.py create-dev-admin
```

Default quick dev credentials:

- email: `admin@local.test`
- password: `TempPass123!`

You can also override them:

```powershell
python -m flask --app run.py create-dev-admin --email you@example.com --password "YourPassword123!"
```

## What Is Included In Version 1

Included now:

- Flask application factory
- blueprint structure: `main`, `auth`, `admin`
- PostgreSQL-backed runtime configuration
- Flask-Migrate migration setup
- public quote request form
- thank-you page
- image upload handling with extension and content validation
- admin authentication with hashed passwords
- admin dashboard
- request detail page
- status updates
- internal notes
- CLI admin bootstrap commands
- email hook stubs
- focused pytest coverage for the main flows

Not included in version 1:

- React frontend
- JSON API layer
- multi-tenancy
- CRM features
- customer portal
- payments
- scheduling
- SMS
- advanced analytics
- SaaS billing

## Testing

Run the focused test suite:

```powershell
python -m pytest tests/test_quote_requests.py -q
```

Or run all tests:

```powershell
python -m pytest
```

Note: tests use SQLite and temporary files so they stay fast and isolated from the local PostgreSQL development database.
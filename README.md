# Quote Request System

Reusable Flask starter for service businesses that need a clean quote intake form and a lightweight admin workflow. It supports PostgreSQL through `DATABASE_URL`, with a local SQLite default so the skeleton runs immediately.

## Stack

- Flask application factory
- SQLAlchemy with local SQLite default and PostgreSQL support via `DATABASE_URL`
- Flask-Migrate for migrations
- Flask-Login for admin auth
- Jinja templates with server-rendered HTML
- File uploads for request photos
- Email notification hooks ready for integration

## Features

- Public quote request form with photo uploads
- Thank-you page after submission
- Admin login/logout
- Request dashboard and request detail page
- Status updates and internal notes
- Customer/admin email hook stubs
- CLI command to create the first admin user
- Small pytest base covering the primary flow

## Project structure

```text
app/
  __init__.py
  cli.py
  config.py
  extensions.py
  admin/
  auth/
  forms/
  main/
  models/
  services/
  static/
  templates/
migrations/
tests/
run.py
wsgi.py
```

## Setup

1. Copy `.env.example` to `.env` and update the values.
2. Optional: create a PostgreSQL database named `quote_requests` and set `DATABASE_URL` if you want Postgres locally.
3. Install dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. Initialize the database:

   ```bash
   flask --app run.py db upgrade
   ```

5. Create an admin user:

   ```bash
   flask --app run.py create-admin
   ```

6. Run the app:

   ```bash
   flask --app run.py run
   ```

## Customization points

- Update `COMPANY_NAME` in `.env` for branding.
- Set `DATABASE_URL` in `.env` to use PostgreSQL instead of the default local SQLite database.
- Adjust form labels/fields in `app/forms/quote_request.py`.
- Replace logging stubs in `app/services/email_hooks.py` with a real mailer.
- Extend status values in `app/models/quote_request.py` and `app/forms/admin.py` if needed.

## Testing

Run:

```bash
pytest
```
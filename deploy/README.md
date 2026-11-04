# Deploying to a DigitalOcean droplet

A single small business site, one droplet, one database. Follow this top to bottom on a
fresh Ubuntu 24.04 box. Everything here is testable; nothing is a guess about a service
you have not seen yet.

Assumed: a droplet (1 vCPU / 1 GB is enough to start, 2 GB is comfortable), a domain you
control, and SSH access as a sudo user.

---

## 1. Base packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip nginx postgresql postgresql-contrib \
                    build-essential libpq-dev certbot python3-certbot-nginx git
```

Create the service account and directories:

```bash
sudo adduser --system --group --home /srv/quoterequests quoterequests
sudo mkdir -p /srv/quoterequests
sudo chown quoterequests:quoterequests /srv/quoterequests
```

## 2. Database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER quote_requests WITH PASSWORD 'replace-me';
CREATE DATABASE quote_requests OWNER quote_requests;
SQL
```

No need to grant CREATEDB - the rehearsals work inside a schema (see the checklist).

## 3. Code and environment

```bash
sudo -u quoterequests git clone <repo-url> /srv/quoterequests
cd /srv/quoterequests
sudo -u quoterequests python3 -m venv .venv
sudo -u quoterequests .venv/bin/pip install -r requirements-server.txt
```

Create `/srv/quoterequests/.env` (mode 600, owned by quoterequests) from `.env.example`,
then set at minimum:

```
FLASK_ENV=production
SECRET_KEY=<64 random hex, unique to this customer>
DATABASE_URL=postgresql+psycopg://quote_requests:replace-me@localhost:5432/quote_requests
TRUST_PROXY=true
BUSINESS_NAME=...
BUSINESS_PHONE=...
BUSINESS_EMAIL=...
ADMIN_NOTIFICATION_EMAIL=...
DEFAULT_FROM_EMAIL=...
EMAIL_ENABLED=true
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...   # the Brevo SMTP key, not the account password
ENABLE_*=true|false  # only the modules this customer bought
RECAPTCHA_ENABLED=true
RECAPTCHA_SITE_KEY=...
RECAPTCHA_SECRET_KEY=...
```

`TRUST_PROXY=true` matters: without it the app sees every request as coming from
127.0.0.1, which breaks per-client rate limiting.

Generate the key with `python3 -c "import secrets; print(secrets.token_hex(32))"`.

## 4. Schema and admin account

```bash
cd /srv/quoterequests
sudo -u quoterequests .venv/bin/python scripts/rehearse_migrations.py --smoke
sudo -u quoterequests .venv/bin/flask --app wsgi db upgrade
sudo -u quoterequests .venv/bin/flask --app wsgi create-admin
```

The rehearsal proves the migrations before they touch the real database. Run it on the
droplet, not just on your laptop.

## 5. systemd

```bash
sudo cp deploy/quoterequests.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quoterequests
sudo systemctl status quoterequests --no-pager
curl -I http://127.0.0.1:8000/          # expect a 200 from gunicorn
```

Logs: `journalctl -u quoterequests -f`.

## 6. nginx and TLS

```bash
sudo cp deploy/nginx-quoterequests.conf /etc/nginx/sites-available/quoterequests
sudo ln -s /etc/nginx/sites-available/quoterequests /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo sed -i 's/example.com/your-domain.com/g' /etc/nginx/sites-available/quoterequests
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

certbot rewrites the certificate paths and reloads nginx. It also renews on a timer by
default - confirm with `systemctl list-timers | grep certbot`.

## 7. Backups

```bash
sudo -u quoterequests mkdir -p /srv/quoterequests/backups
sudo crontab -u quoterequests -e
```

```
15 2 * * *  cd /srv/quoterequests && .venv/bin/python scripts/backup.py --out /srv/backups --keep 14 >> /var/log/quoterequests-backup.log 2>&1
30 2 * * 0  cd /srv/quoterequests && .venv/bin/python scripts/restore_check.py >> /var/log/quoterequests-restore.log 2>&1
```

Put the backup directory on a DigitalOcean volume or sync it off the droplet - a backup
that lives only on the machine it backs up is not a backup.

## 8. First-run verification

Work through `DEPLOYMENT_CHECKLIST.md` - particularly:

1. `https://your-domain.com` loads over a valid certificate.
2. Log in; the browser shows the session cookie as Secure.
3. Submit the public quote form; the request appears in the dashboard.
4. Confirm both emails arrive (deploy gate 8).
5. Open a request photo, copy its URL, load it in a private window: login redirect.
   Swap `/admin/media/` for `/static/uploads/`: 404.
6. Run the UI sweep locally against a seeded copy (`python scripts/ui_sweep.py`) - it
   seeds its own database, so it is a layout check, not a production probe. Live checks
   are steps 1-5 and the checklist.
7. Submit the quote form six times: the sixth shows the 429 page.

## 9. Ongoing

- `sudo systemctl status quoterequests` after any code change; deploy with
  `git pull && .venv/bin/pip install -r requirements-server.txt && flask --app wsgi db upgrade && sudo systemctl restart quoterequests`.
- Watch `journalctl -u quoterequests` and nginx's error log for the first week.
- Re-run the deployment checklist whenever a module flag changes.

---

## Notes on this configuration

- **Two gunicorn workers, four threads.** Small and predictable. The in-app rate limiter
  keeps counters per worker, so raising workers multiplies the effective limit.
- **Loopback binding.** gunicorn listens on 127.0.0.1:8000; nothing reaches it except
  nginx. Never expose 8000 in the firewall.
- **Uploads stay private through two layers.** nginx returns 404 for
  `/static/uploads/quote_requests/` and `/static/uploads/customers/`, and the app blocks
  the same prefixes and serves authorised files from `/admin/media/`.
- **`client_max_body_size 26m`** is deliberately just above the app's 25 MB cap so the
  user gets the branded 413 page rather than nginx's default error.

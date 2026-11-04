"""Gunicorn configuration for a small single-business deployment.

    gunicorn --config deploy/gunicorn.conf.py wsgi:application

Binds to loopback only: nginx owns :80/:443 and proxies to this process, so the app is
never directly reachable from the internet.

Worker count is deliberately small. The in-app rate limiter keeps counters per worker,
so each extra worker multiplies the effective limit (see app/services/rate_limit.py).
Two workers is enough for a quote form and an admin dashboard.
"""

import multiprocessing  # noqa: F401 - kept for anyone tuning workers upward
import os

bind = "127.0.0.1:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

timeout = 60
graceful_timeout = 30
keepalive = 5

max_requests = 1000
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" %(D)sus'

# systemd sends SIGTERM; let in-flight requests finish.
def on_exit(server):  # noqa: ANN001, D103
    server.log.info("gunicorn shutting down")

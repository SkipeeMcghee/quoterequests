"""Platform authentication is independent of tenant Flask-Login identities."""

import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

from flask import current_app, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user
from itsdangerous import BadData, URLSafeTimedSerializer

from app.admin import bp as admin_bp
from app.extensions import db
from app.models import User
from app.superadmin import bp
from app.superadmin import operations
from app.tenancy import get_current_tenant, get_registry


def audit(action, *, tenant=None, outcome="success"):
    current_app.logger.info(
        "superadmin.%s target=%s outcome=%s", action, tenant, outcome,
        extra={"event": f"superadmin.{action}", "target_tenant": tenant,
               "outcome": outcome, "actor": "superadmin"},
    )


def login_limit():
    """Called by the platform boundary before CSRF, including invalid-token attempts."""
    if request.method != "POST" or request.form.get("action", "login") != "login":
        return None
    from app.services.rate_limit import _STORE
    window = int(current_app.config.get("RATE_LIMIT_LOGIN_WINDOW_SECONDS") or 300)
    limit = int(current_app.config.get("RATE_LIMIT_LOGIN_REQUESTS") or 10)
    # remote_addr is already processed by ProxyFix; never trust raw forwarded headers.
    key = f"platform:login:{request.remote_addr or 'unknown'}"
    if _STORE.hit(key, window) > limit:
        audit("login", outcome="rate_limited")
        return "Too many login attempts.", 429, {"Retry-After": str(window)}
    return None


def _session_proof():
    password = current_app.config.get("SUPERADMIN_PASSWORD", "")
    if not isinstance(password, str) or not password.strip():
        return None
    scope = f"superadmin-session\0{request.host.lower()}\0{password}"
    secret = current_app.secret_key
    return hmac.new(secret.encode() if isinstance(secret, str) else secret,
                    scope.encode(), hashlib.sha256).hexdigest()


def authenticated():
    proof = _session_proof()
    value = session.get("_superadmin_authenticated")
    return proof is not None and isinstance(value, str) and hmac.compare_digest(value, proof)


def _serializer():
    # Rotating either secret invalidates all outstanding handoffs.
    key = hmac.new(str(current_app.secret_key).encode(),
                   str(current_app.config.get("SUPERADMIN_PASSWORD", "")).encode(), hashlib.sha256).digest()
    return URLSafeTimedSerializer(key, salt="superadmin-tenant-handoff-v1")


def _handoff_store():
    root = Path(current_app.instance_path) / "platform-control"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError("Invalid platform storage path.")
    path = root / "handoffs.sqlite3"
    if path.is_symlink():
        raise ValueError("Invalid platform storage path.")
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS handoffs (nonce TEXT PRIMARY KEY, tenant TEXT NOT NULL, expires REAL NOT NULL)")
    return connection


def issue_handoff(tenant):
    if not tenant.enabled:
        raise ValueError("Enable the tenant before impersonating.")
    with operations.operator_context(tenant):
        user = User.query.filter_by(is_active=True).order_by(User.id).first()
        if user is None:
            raise ValueError("The tenant has no active admin account.")
        user_id = user.id
    nonce = secrets.token_urlsafe(32)
    ttl = int(current_app.config["SUPERADMIN_HANDOFF_TTL_SECONDS"])
    connection = _handoff_store()
    try:
        with connection:
            connection.execute("DELETE FROM handoffs WHERE expires < ?", (time.time(),))
            connection.execute("INSERT INTO handoffs VALUES (?, ?, ?)", (nonce, tenant.slug, time.time() + ttl))
    finally:
        connection.close()
    token = _serializer().dumps({"tenant": tenant.slug, "user": user_id, "nonce": nonce})
    # Use a registered host, never an arbitrary configured redirect/origin.
    host = tenant.hosts[0]
    from app.tenancy import normalize_host
    normalized = normalize_host(host)
    host = f"[{normalized}]" if ":" in normalized else normalized
    return f"https://{host}/admin/superadmin-handoff?{urlencode({'token': token})}"


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@bp.route("", methods=["GET", "POST"])
@bp.route("/", methods=["GET", "POST"])
def dashboard():
    from flask import flash
    action = request.form.get("action", "login")
    if request.method == "POST" and action == "login":
        expected = str(current_app.config["SUPERADMIN_PASSWORD"]).encode()
        if not hmac.compare_digest(request.form.get("password", "").encode(), expected):
            audit("login", outcome="rejected")
            return render_template("superadmin/dashboard.html", authenticated=False, error="Invalid password."), 401
        session.clear()
        session["_remember"] = "clear"
        session["_superadmin_authenticated"] = _session_proof()
        audit("login")
        return redirect(url_for("superadmin.dashboard"))
    if not authenticated():
        if request.method == "POST":
            audit(action if action in {"create", "edit", "toggle", "upgrade", "backup", "reset_demo", "impersonate", "logout"} else "unknown", outcome="unauthenticated")
            return "Platform authentication required.", 401
        return render_template("superadmin/dashboard.html", authenticated=False)
    if request.method == "POST":
        slug = request.form.get("slug", "")
        allowed = {"create", "edit", "toggle", "upgrade", "backup", "reset_demo", "impersonate", "logout"}
        if action not in allowed:
            audit("unknown", outcome="rejected")
            return "Unknown action.", 400
        try:
            if action == "logout":
                session.clear()
            elif action == "create":
                operations.provision_tenant(_operator_form())
                flash(f"Tenant {slug} provisioned.", "success")
            else:
                tenant = get_registry().tenants.get(slug)
                if tenant is None:
                    raise ValueError("Unknown tenant.")
                if action in {"edit", "toggle"}:
                    operations.update_tenant(slug, _operator_form(), toggle=action == "toggle")
                elif action == "upgrade":
                    operations.migrate_tenant(tenant)
                elif action == "backup":
                    artifact = operations.backup_tenant(tenant)
                    flash(f"Backup created: {artifact}", "success")
                elif action == "reset_demo":
                    operations.reset_demo(tenant, request.form.get("confirmation", ""))
                elif action == "impersonate":
                    target = issue_handoff(tenant)
                    audit("impersonate", tenant=slug, outcome="issued")
                    return redirect(target)
                flash(f"{action}: {slug} complete.", "success")
            audit(action, tenant=slug or None)
        except ValueError as exc:
            audit(action, tenant=slug or None, outcome="failed")
            flash(str(exc), "error")
        except Exception:
            audit(action, tenant=slug or None, outcome="failed")
            flash("Operator action failed; check platform configuration.", "error")
        return redirect(url_for("superadmin.dashboard"))
    rows = operations.fleet_rows()
    registry_path = current_app.config.get("TENANT_REGISTRY_FILE", "")
    path = Path(registry_path) if registry_path else None
    status = "present" if path and path.is_file() else "not created" if path else "not configured (read-only registry)"
    return render_template("superadmin/dashboard.html", authenticated=True, rows=rows,
                           flags=operations.FEATURE_FLAGS, identities=operations.IDENTITY_FIELDS,
                           registry_path=registry_path or "—", registry_status=status,
                           enabled=sum(row["tenant"].enabled for row in rows),
                           health="degraded" if any(row["error"] or row["migration_status"] != "current" for row in rows) else "ok")


def _operator_form():
    form = request.form.to_dict()
    for flag in operations.FEATURE_FLAGS:
        form[flag] = flag in request.form
    return form


@admin_bp.get("/superadmin-handoff")
def consume_handoff():
    tenant = get_current_tenant()
    password = current_app.config.get("SUPERADMIN_PASSWORD", "")
    try:
        if not isinstance(password, str) or not password.strip():
            raise ValueError()
        data = _serializer().loads(request.args.get("token", ""), max_age=int(current_app.config["SUPERADMIN_HANDOFF_TTL_SECONDS"]))
        if not isinstance(data, dict) or data.get("tenant") != tenant.slug or not isinstance(data.get("user"), int) or not isinstance(data.get("nonce"), str):
            raise ValueError()
        user = db.session.get(User, data["user"])
        if user is None or not user.is_active:
            raise ValueError()
        connection = _handoff_store()
        try:
            with connection:
                consumed = connection.execute("DELETE FROM handoffs WHERE nonce = ? AND tenant = ? AND expires >= ?",
                                              (data["nonce"], tenant.slug, time.time())).rowcount
            if consumed != 1:
                raise ValueError()
        finally:
            connection.close()
    except (BadData, ValueError, TypeError, sqlite3.Error):
        audit("impersonate", tenant=tenant.slug, outcome="rejected")
        return "Invalid or expired handoff.", 403, {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    logout_user()
    session.clear()
    session["_remember"] = "clear"
    login_user(user, remember=False, fresh=True)
    session["_superadmin_impersonating"] = tenant.slug
    audit("impersonate", tenant=tenant.slug, outcome="consumed")
    response = redirect(url_for("admin.dashboard"))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@admin_bp.post("/exit-impersonation")
def exit_impersonation():
    tenant = get_current_tenant()
    if session.get("_superadmin_impersonating") != tenant.slug:
        return "No impersonation session.", 403
    logout_user()
    session.clear()
    session["_remember"] = "clear"
    audit("exit_impersonation", tenant=tenant.slug)
    return redirect(url_for("admin.admin_entry"))
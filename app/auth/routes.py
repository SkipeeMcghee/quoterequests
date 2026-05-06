from urllib.parse import urlparse

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask.typing import ResponseReturnValue

from app.auth import bp
from app.forms.auth import LoginForm
from app.services.auth import authenticate_user


def _post_login_redirect_target(next_url: str | None) -> str:
    admin_entry_url = url_for("admin.admin_entry")
    if next_url == admin_entry_url:
        return url_for("admin.dashboard")
    return next_url or url_for("admin.dashboard")


def handle_admin_login() -> ResponseReturnValue:
    next_url = _get_safe_next_url()

    if current_user.is_authenticated:
        return redirect(_post_login_redirect_target(next_url))

    form = LoginForm()
    if form.validate_on_submit():
        user = authenticate_user(form.email.data, form.password.data)
        if user is None:
            flash("Invalid email or password.", "error")
        else:
            login_user(user, remember=form.remember_me.data)
            flash("You are now signed in.", "success")
            return redirect(_post_login_redirect_target(next_url))

    return render_template("auth/login.html", form=form, next_url=next_url)


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = _get_safe_next_url()
    if request.method == "GET":
        return redirect(url_for("admin.admin_entry", next=next_url) if next_url else url_for("admin.admin_entry"))

    return handle_admin_login()


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("admin.admin_entry"))


def _get_safe_next_url() -> str | None:
    next_url = request.args.get("next") or request.form.get("next")
    if not next_url:
        return None

    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return None

    return next_url
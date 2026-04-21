from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import bp
from app.forms.auth import LoginForm
from app.services.auth import authenticate_user


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = authenticate_user(form.email.data, form.password.data)
        if user is None:
            flash("Invalid email or password.", "error")
        else:
            login_user(user, remember=form.remember_me.data)
            flash("You are now signed in.", "success")
            return redirect(url_for("admin.dashboard"))

    return render_template("auth/login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
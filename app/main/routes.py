from flask import current_app, flash, redirect, render_template, url_for
from werkzeug.exceptions import BadRequest

from app.forms.quote_request import QuoteRequestForm
from app.main import bp
from app.services.quotes import create_quote_request


@bp.get("/")
def index():
    return render_template("main/index.html")


@bp.route("/quote-request", methods=["GET", "POST"])
def quote_request():
    form = QuoteRequestForm()
    if form.validate_on_submit():
        try:
            create_quote_request(form, form.photos.data)
        except BadRequest as exc:
            form.photos.errors.append(exc.description)
            flash(exc.description, "error")
        else:
            return redirect(url_for("main.thank_you"))

    return render_template("main/quote_request.html", form=form)


@bp.route("/schedule-work", methods=["GET", "POST"])
def schedule_work():
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("main.quote_request"))

    form = QuoteRequestForm()
    if form.validate_on_submit():
        try:
            create_quote_request(form, form.photos.data)
        except BadRequest as exc:
            form.photos.errors.append(exc.description)
            flash(exc.description, "error")
        else:
            return redirect(url_for("main.thank_you"))

    return render_template("main/schedule_work.html", form=form)


@bp.get("/thank-you")
def thank_you():
    return render_template("main/thank_you.html")
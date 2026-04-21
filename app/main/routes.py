from flask import redirect, render_template, url_for

from app.forms.quote_request import QuoteRequestForm
from app.main import bp
from app.services.quotes import create_quote_request


@bp.get("/")
def index():
    return redirect(url_for("main.quote_request"))


@bp.route("/quote-request", methods=["GET", "POST"])
def quote_request():
    form = QuoteRequestForm()
    if form.validate_on_submit():
        create_quote_request(form, form.photos.data)
        return redirect(url_for("main.thank_you"))

    return render_template("main/quote_request.html", form=form)


@bp.get("/thank-you")
def thank_you():
    return render_template("main/thank_you.html")
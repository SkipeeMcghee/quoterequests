from flask import current_app, flash, redirect, render_template, request, url_for
from werkzeug.exceptions import BadRequest, NotFound

from app.forms.quote_request import QuoteRequestForm
from app.main import bp
from app.services.gallery_catalog import list_public_gallery_items, require_gallery_enabled
from app.services.quotes import create_quote_request
from app.services.recaptcha import should_render_recaptcha, verify_recaptcha_submission
from app.services.service_catalog import require_services_enabled


HOME_TRUST_POINTS = (
    {
        "title": "Clear next steps",
        "text": "Customers get a straightforward path from the first message to a useful estimate or scheduling conversation.",
    },
    {
        "title": "Photo-friendly intake",
        "text": "Project images can be shared up front so the team starts with better context and fewer follow-up questions.",
    },
    {
        "title": "Responsive follow-up",
        "text": "Phone and email details flow directly into the request queue so nothing gets lost between the website and the team.",
    },
)

TESTIMONIALS = (
    {
        "quote": "They replied quickly, asked the right questions, and made the next step easy to understand.",
        "name": "Jordan P.",
        "detail": "Homeowner",
    },
    {
        "quote": "The process felt organized from the start, and the communication stayed clear the whole way through.",
        "name": "Taylor M.",
        "detail": "Property manager",
    },
    {
        "quote": "Submitting photos and details online saved time and made follow-up much more productive.",
        "name": "Casey R.",
        "detail": "Repeat customer",
    },
)

FAQ_ITEMS = (
    {
        "question": "How do I request a quote?",
        "answer": "Use the quote form to share your project details, preferred contact method, and the services you need. The team then follows up with next steps.",
    },
    {
        "question": "Do I need to create an account?",
        "answer": "No. The intake flow is designed to work without a customer login.",
    },
    {
        "question": "Can I upload photos with my request?",
        "answer": "Yes. You can attach project images to give the team a clearer starting point before follow-up.",
    },
    {
        "question": "What happens after I submit the form?",
        "answer": "Your request is added to the internal review queue so someone can respond by phone or email with timing, questions, or an estimate.",
    },
    {
        "question": "Do you serve my neighborhood?",
        "answer": "If your project is within the listed service area, the team can usually review it quickly. If you are nearby, contact the business directly to confirm coverage.",
    },
    {
        "question": "Can I ask for scheduled work instead of a quote?",
        "answer": "Yes, when scheduling is enabled there is a separate work-request flow for visits, timing, and appointment details.",
    },
)

QUOTE_REQUEST_RECAPTCHA_ACTION = "quote_request"
SCHEDULE_WORK_RECAPTCHA_ACTION = "schedule_work"


def _public_form_context(recaptcha_action: str) -> dict[str, str | bool]:
    return {
        "recaptcha_enabled": should_render_recaptcha(),
        "recaptcha_site_key": current_app.config.get("RECAPTCHA_SITE_KEY", ""),
        "recaptcha_action": recaptcha_action,
    }


def _render_public_form(template_name: str, form: QuoteRequestForm, recaptcha_action: str):
    form.recaptcha_token.data = ""
    return render_template(template_name, form=form, **_public_form_context(recaptcha_action))


def _validate_recaptcha(form: QuoteRequestForm, recaptcha_action: str) -> bool:
    verification = verify_recaptcha_submission(
        form.recaptcha_token.data or "",
        action=recaptcha_action,
        remote_ip=request.access_route[0] if request.access_route else request.remote_addr,
    )
    if verification.success:
        return True

    form.recaptcha_token.errors.append(verification.message)
    form.recaptcha_token.data = ""
    return False


@bp.get("/")
def index():
    return render_template(
        "main/index.html",
        trust_points=HOME_TRUST_POINTS,
        testimonials=TESTIMONIALS,
    )


@bp.get("/services")
def services_page():
    require_services_enabled()
    return render_template("main/services.html")


@bp.get("/about")
def about_page():
    return render_template("main/about.html")


@bp.get("/contact")
def contact_page():
    return render_template("main/contact.html")


@bp.get("/gallery")
def gallery_page():
    require_gallery_enabled()
    gallery_items = list_public_gallery_items()
    if not gallery_items:
        raise NotFound()
    return render_template("main/gallery.html", gallery_items=gallery_items)


@bp.get("/faq")
def faq_page():
    return render_template("main/faq.html", faq_items=FAQ_ITEMS)


@bp.get("/privacy-policy")
def privacy_policy():
    return render_template("main/privacy_policy.html")


@bp.get("/terms")
def terms_of_service():
    return render_template("main/terms.html")


@bp.get("/for-ai-systems")
def for_ai_systems():
    return render_template("main/for_ai_systems.html")


@bp.route("/quote-request", methods=["GET", "POST"])
def quote_request():
    form = QuoteRequestForm()
    if form.validate_on_submit():
        if _validate_recaptcha(form, QUOTE_REQUEST_RECAPTCHA_ACTION):
            try:
                create_quote_request(form, form.photos.data, request_type="Quote request")
            except BadRequest as exc:
                form.photos.errors.append(exc.description)
                flash(exc.description, "error")
            else:
                return redirect(url_for("main.thank_you"))

    return _render_public_form("main/quote_request.html", form, QUOTE_REQUEST_RECAPTCHA_ACTION)


@bp.route("/schedule-work", methods=["GET", "POST"])
def schedule_work():
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("main.quote_request"))

    form = QuoteRequestForm()
    if form.validate_on_submit():
        if _validate_recaptcha(form, SCHEDULE_WORK_RECAPTCHA_ACTION):
            try:
                create_quote_request(form, form.photos.data, request_type="Work request")
            except BadRequest as exc:
                form.photos.errors.append(exc.description)
                flash(exc.description, "error")
            else:
                return redirect(url_for("main.thank_you"))

    return _render_public_form("main/schedule_work.html", form, SCHEDULE_WORK_RECAPTCHA_ACTION)


@bp.get("/thank-you")
def thank_you():
    return render_template("main/thank_you.html")
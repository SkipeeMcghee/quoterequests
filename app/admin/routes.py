from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.admin import bp
from app.forms.admin import NoteForm, StatusUpdateForm
from app.services.admin_requests import add_request_note, get_quote_request, list_quote_requests, update_request_status


@bp.get("/")
@login_required
def dashboard():
    quote_requests = list_quote_requests()
    return render_template("admin/dashboard.html", quote_requests=quote_requests)


@bp.get("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    quote_request = get_quote_request(request_id)
    status_form = StatusUpdateForm(status=quote_request.status)
    note_form = NoteForm()
    return render_template(
        "admin/request_detail.html",
        quote_request=quote_request,
        status_form=status_form,
        note_form=note_form,
    )


@bp.post("/requests/<int:request_id>/status")
@login_required
def update_status(request_id: int):
    form = StatusUpdateForm()
    if form.validate_on_submit():
        update_request_status(request_id, form.status.data)
        flash("Request status updated.", "success")
    else:
        flash("Choose a valid status.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="status"))


@bp.post("/requests/<int:request_id>/notes")
@login_required
def create_note(request_id: int):
    form = NoteForm()
    if form.validate_on_submit():
        add_request_note(request_id, form.note_text.data, current_user)
        flash("Note added.", "success")
    else:
        flash("Enter a note before saving.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="notes"))
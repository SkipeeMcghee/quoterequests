from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.admin import bp
from app.forms.admin import (
    AppointmentForm,
    AppointmentStatusForm,
    NoteForm,
    RescheduleAppointmentForm,
    StatusUpdateForm,
)
from app.services.admin_requests import (
    add_request_note,
    create_appointment,
    get_appointment,
    get_quote_request,
    list_quote_requests,
    reschedule_appointment,
    update_appointment,
    update_appointment_status,
    update_request_status,
)


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
    appointment_form = None
    appointment_status_form = None
    reschedule_form = None

    if current_app.config.get("ENABLE_SCHEDULING"):
        if quote_request.current_appointment:
            appointment_form = AppointmentForm(
                obj=quote_request.current_appointment,
                prefix="edit",
            )
            appointment_status_form = AppointmentStatusForm(status=quote_request.current_appointment.status)
            reschedule_form = RescheduleAppointmentForm(prefix="reschedule")
        else:
            appointment_form = AppointmentForm(prefix="create")

    return render_template(
        "admin/request_detail.html",
        quote_request=quote_request,
        status_form=status_form,
        note_form=note_form,
        appointment_form=appointment_form,
        appointment_status_form=appointment_status_form,
        reschedule_form=reschedule_form,
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


@bp.post("/requests/<int:request_id>/appointments")
@login_required
def create_appointment_route(request_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.request_detail", request_id=request_id))

    form = AppointmentForm(prefix="create")
    if form.validate_on_submit():
        if not form.requested_date.data:
            flash("Enter a requested date before saving.", "error")
        else:
            create_appointment(
                request_id,
                requested_date=form.requested_date.data,
                requested_time_window=(form.requested_time_window.data or "").strip() or None,
                customer_notes=(form.customer_notes.data or "").strip() or None,
                internal_notes=(form.internal_notes.data or "").strip() or None,
                confirmed_date=form.confirmed_date.data,
                confirmed_time_window=(form.confirmed_time_window.data or "").strip() or None,
            )
            flash("Appointment created.", "success")
    else:
        flash("Correct the appointment details and try again.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="scheduling"))


@bp.post("/appointments/<int:appointment_id>/status")
@login_required
def update_appointment_status_route(appointment_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.dashboard"))

    form = AppointmentStatusForm()
    if form.validate_on_submit():
        update_appointment_status(appointment_id, form.status.data)
        flash("Appointment status updated.", "success")
    else:
        flash("Choose a valid appointment status.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.request_detail", request_id=appointment.quote_request_id, _anchor="scheduling"))


@bp.post("/appointments/<int:appointment_id>/edit")
@login_required
def edit_appointment_route(appointment_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.dashboard"))

    form = AppointmentForm(prefix="edit")
    if form.validate_on_submit():
        update_appointment(
            appointment_id,
            requested_date=form.requested_date.data,
            requested_time_window=(form.requested_time_window.data or "").strip() or None,
            confirmed_date=form.confirmed_date.data,
            confirmed_time_window=(form.confirmed_time_window.data or "").strip() or None,
            customer_notes=(form.customer_notes.data or "").strip() or None,
            internal_notes=(form.internal_notes.data or "").strip() or None,
        )
        flash("Appointment details updated.", "success")
    else:
        flash("Correct the appointment details and try again.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.request_detail", request_id=appointment.quote_request_id, _anchor="scheduling"))


@bp.post("/appointments/<int:appointment_id>/reschedule")
@login_required
def reschedule_appointment_route(appointment_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.dashboard"))

    form = RescheduleAppointmentForm(prefix="reschedule")
    if form.validate_on_submit():
        if not form.requested_date.data:
            flash("Enter a reschedule date before saving.", "error")
        else:
            reschedule_appointment(
                appointment_id,
                requested_date=form.requested_date.data,
                requested_time_window=(form.requested_time_window.data or "").strip() or None,
                internal_notes=(form.internal_notes.data or "").strip() or None,
            )
            flash("Appointment rescheduled.", "success")
    else:
        flash("Correct the reschedule details and try again.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.request_detail", request_id=appointment.quote_request_id, _anchor="scheduling"))


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
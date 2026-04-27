from calendar import month_name, monthcalendar
from datetime import date, time, timedelta
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin import bp
from app.forms.admin import (
    AppointmentForm,
    AppointmentStatusForm,
    CreateCustomerForm,
    CustomerBillingForm,
    CustomerFieldForm,
    CustomerNoteForm,
    DeleteNoteForm,
    LastContactedForm,
    LinkCustomerForm,
    MergeCustomerForm,
    NoteForm,
    RecurringWorkGenerationForm,
    RescheduleAppointmentForm,
    SetPrimaryFieldForm,
    StatusUpdateForm,
)
from app.services.admin_requests import (
    add_customer_field,
    add_customer_note,
    add_request_note,
    create_appointment,
    create_customer_from_quote_request,
    delete_request_note,
    find_customer_matches_for_request,
    get_appointment,
    get_customer,
    get_quote_request,
    get_recurring_work,
    get_request_note,
    list_customers,
    list_quote_requests,
    list_recurring_works,
    list_appointments_for_day,
    list_appointments_for_month,
    merge_customers,
    reschedule_appointment,
    set_primary_customer_field,
    update_appointment,
    update_appointment_status,
    update_customer_billing,
    generate_recurring_appointments_for_customer,
    update_last_contacted_on,
    update_request_note,
    update_request_status,
)


@bp.get("/")
@login_required
def dashboard():
    quote_requests = list_quote_requests()
    return render_template("admin/dashboard.html", quote_requests=quote_requests)


@bp.get("/calendar")
@login_required
def calendar_view():
    if not current_app.config.get("ENABLE_CALENDAR"):
        return redirect(url_for("admin.dashboard"))

    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    today = date.today()
    if year is None or month is None:
        year = today.year
        month = today.month

    try:
        appointments = list_appointments_for_month(year, month)
    except ValueError:
        return redirect(url_for("admin.calendar_view"))

    month_matrix = monthcalendar(year, month)
    appointments_by_date = {}
    for appointment in appointments:
        appointments_by_date.setdefault(appointment.scheduled_date, []).append(appointment)

    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    return render_template(
        "admin/calendar.html",
        year=year,
        month=month,
        month_name=month_name[month],
        month_matrix=month_matrix,
        appointments_by_date=appointments_by_date,
        today=today,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        day_names=day_names,
        date=date,
    )


@bp.get("/calendar/<int:year>/<int:month>/<int:day>")
@login_required
def calendar_day_view(year: int, month: int, day: int):
    if not current_app.config.get("ENABLE_CALENDAR"):
        return redirect(url_for("admin.dashboard"))

    try:
        appointments = list_appointments_for_day(year, month, day)
        view_date = date(year, month, day)
    except ValueError:
        return redirect(url_for("admin.calendar_view"))

    day_start = 6 * 60
    day_end = 20 * 60
    total_minutes = day_end - day_start
    scheduled_appointments = []
    unscheduled_appointments = []

    for appointment in appointments:
        if not appointment.start_time or not appointment.end_time:
            unscheduled_appointments.append(appointment)
            continue

        start_minutes = appointment.start_time.hour * 60 + appointment.start_time.minute
        end_minutes = appointment.end_time.hour * 60 + appointment.end_time.minute

        if end_minutes <= day_start or start_minutes >= day_end:
            unscheduled_appointments.append(appointment)
            continue

        clipped_start = max(start_minutes, day_start)
        clipped_end = min(end_minutes, day_end)
        if clipped_end <= clipped_start:
            clipped_end = min(clipped_start + 30, day_end)

        scheduled_appointments.append(
            {
                "appointment": appointment,
                "start_minutes": clipped_start,
                "end_minutes": clipped_end,
                "top_percent": ((clipped_start - day_start) / total_minutes) * 100,
                "height_percent": ((clipped_end - clipped_start) / total_minutes) * 100,
                "duration_minutes": clipped_end - clipped_start,
            }
        )

    scheduled_appointments.sort(key=lambda item: (item["start_minutes"], item["end_minutes"]))
    active = []
    for item in scheduled_appointments:
        active = [entry for entry in active if entry["end_minutes"] > item["start_minutes"]]
        used_columns = {entry["column"] for entry in active}
        column = 0
        while column in used_columns:
            column += 1
        item["column"] = column
        active.append(item)
        current_width = len(active)
        for entry in active:
            entry["col_count"] = max(entry.get("col_count", 0), current_width)

    for item in scheduled_appointments:
        width_percent = 100 / item["col_count"]
        item["left_percent"] = item["column"] * width_percent
        item["width_percent"] = width_percent

    prev_date = view_date - timedelta(days=1)
    next_date = view_date + timedelta(days=1)

    return render_template(
        "admin/calendar_day.html",
        view_date=view_date,
        scheduled_appointments=scheduled_appointments,
        unscheduled_appointments=unscheduled_appointments,
        prev_date=prev_date,
        next_date=next_date,
        year=year,
        month=month,
        day_start=6,
        day_end=20,
    )


@bp.get("/appointments/<int:appointment_id>")
@login_required
def appointment_detail(appointment_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.dashboard"))

    appointment = get_appointment(appointment_id)
    appointment_form = AppointmentForm(obj=appointment, prefix="edit")
    reschedule_form = RescheduleAppointmentForm(prefix="reschedule")

    history = []
    previous = appointment.previous_appointment
    while previous is not None:
        history.append(previous)
        previous = previous.previous_appointment
    history.reverse()

    future_reschedules = sorted(
        appointment.rescheduled_appointments,
        key=lambda item: item.created_at,
    )

    calendar_year = appointment.scheduled_date.year if appointment.scheduled_date else date.today().year
    calendar_month = appointment.scheduled_date.month if appointment.scheduled_date else date.today().month

    return render_template(
        "admin/appointment_detail.html",
        appointment=appointment,
        appointment_form=appointment_form,
        reschedule_form=reschedule_form,
        history=history,
        future_reschedules=future_reschedules,
        calendar_year=calendar_year,
        calendar_month=calendar_month,
        today=date.today(),
    )


@bp.get("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    quote_request = get_quote_request(request_id)
    status_form = StatusUpdateForm(status=quote_request.status)
    note_form = NoteForm()
    last_contacted_form = LastContactedForm(obj=quote_request)
    appointment_form = None
    appointment_status_form = None
    reschedule_form = None

    if current_app.config.get("ENABLE_SCHEDULING"):
        if quote_request.current_appointment:
            appointment_form = AppointmentForm(
                obj=quote_request.current_appointment,
                prefix="edit",
            )
            appointment_form.customer_id.choices = [
                (quote_request.customer.id, quote_request.customer.primary_name or 'Customer')
            ] if quote_request.customer else []
            if quote_request.customer:
                appointment_form.customer_id.data = quote_request.customer.id
            appointment_status_form = AppointmentStatusForm(status=quote_request.current_appointment.status)
            reschedule_form = RescheduleAppointmentForm(prefix="reschedule")
        else:
            appointment_form = AppointmentForm(prefix="create")
            if quote_request.customer:
                appointment_form.customer_id.choices = [
                    (quote_request.customer.id, quote_request.customer.primary_name or 'Customer')
                ]
                appointment_form.customer_id.data = quote_request.customer.id
            else:
                appointment_form.customer_id.choices = [
                    (customer.id, f"{customer.primary_name or 'Unnamed'} — {customer.primary_email or 'no email'} — {customer.primary_phone or 'no phone'}")
                    for customer in list_customers()
                ]

    edit_note_forms = {
        note.id: NoteForm(prefix=f"edit-note-{note.id}", obj=note)
        for note in quote_request.notes
        if note.created_by == current_user.id
    }
    delete_note_form = DeleteNoteForm(prefix="delete-note")
    link_customer_form = LinkCustomerForm(prefix="link-customer")
    create_customer_form = CreateCustomerForm(prefix="create-customer")
    customer_matches = find_customer_matches_for_request(quote_request)
    customer_billing_form = CustomerBillingForm(
        billing_amount=quote_request.customer.billing_amount if quote_request.customer else None,
        billing_frequency=quote_request.customer.billing_frequency if quote_request.customer else None,
        prefix="customer-billing",
    )
    add_customer_field_form = CustomerFieldForm(prefix="add-customer-field")
    customer_note_form = CustomerNoteForm(prefix="customer-note")
    set_primary_field_form = SetPrimaryFieldForm(prefix="set-primary")

    return render_template(
        "admin/request_detail.html",
        quote_request=quote_request,
        status_form=status_form,
        note_form=note_form,
        delete_note_form=delete_note_form,
        edit_note_forms=edit_note_forms,
        last_contacted_form=last_contacted_form,
        appointment_form=appointment_form,
        appointment_status_form=appointment_status_form,
        reschedule_form=reschedule_form,
        link_customer_form=link_customer_form,
        create_customer_form=create_customer_form,
        customer_matches=customer_matches,
        customer_billing_form=customer_billing_form,
        add_customer_field_form=add_customer_field_form,
        customer_note_form=customer_note_form,
        set_primary_field_form=set_primary_field_form,
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

@bp.post("/notes/<int:note_id>/edit")
@login_required
def edit_note_route(note_id: int):
    note = get_request_note(note_id)
    if note.created_by != current_user.id:
        flash("You can only edit your own notes.", "error")
        return redirect(url_for("admin.request_detail", request_id=note.quote_request_id, _anchor="notes"))

    form = NoteForm(prefix=f"edit-note-{note_id}")
    if form.validate_on_submit():
        update_request_note(note_id, form.note_text.data)
        flash("Note updated.", "success")
    else:
        flash("Correct the note before saving.", "error")

    return redirect(url_for("admin.request_detail", request_id=note.quote_request_id, _anchor="notes"))


@bp.post("/notes/<int:note_id>/delete")
@login_required
def delete_note_route(note_id: int):
    note = get_request_note(note_id)
    if note.created_by != current_user.id:
        flash("You can only delete your own notes.", "error")
        return redirect(url_for("admin.request_detail", request_id=note.quote_request_id, _anchor="notes"))

    form = DeleteNoteForm(prefix=f"delete-note-{note_id}")
    if form.validate_on_submit():
        delete_request_note(note_id)
        flash("Note deleted.", "success")
    else:
        flash("Invalid request.", "error")

    return redirect(url_for("admin.request_detail", request_id=note.quote_request_id, _anchor="notes"))

@bp.post("/requests/<int:request_id>/last-contacted")
@login_required
def update_last_contacted_on_route(request_id: int):
    form = LastContactedForm()
    if form.validate_on_submit():
        update_last_contacted_on(request_id, form.last_contacted_on.data)
        flash("Last contacted date updated.", "success")
    else:
        flash("Enter a valid date or clear the field.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="request-details"))


@bp.post("/requests/<int:request_id>/appointments")
@login_required
def create_appointment_route(request_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.request_detail", request_id=request_id))

    form = AppointmentForm(prefix="create")
    quote_request = get_quote_request(request_id)
    if form.validate_on_submit():
        if quote_request.customer_id is None and not form.customer_id.data:
            flash("Choose a customer or link the request before scheduling.", "error")
        elif not form.scheduled_date.data:
            flash("Enter a scheduled date before saving.", "error")
        else:
            if quote_request.customer_id is None and form.customer_id.data:
                link_quote_request_to_customer(request_id, form.customer_id.data)
            create_appointment(
                request_id,
                requested_date=form.requested_date.data,
                requested_time_window=(form.requested_time_window.data or "").strip() or None,
                customer_notes=(form.customer_notes.data or "").strip() or None,
                internal_notes=(form.internal_notes.data or "").strip() or None,
                confirmed_date=form.confirmed_date.data,
                confirmed_time_window=(form.confirmed_time_window.data or "").strip() or None,
                scheduled_date=form.scheduled_date.data,
                start_time=form.start_time.data,
                end_time=form.end_time.data,
                status=form.status.data,
            )
            flash("Appointment created.", "success")
    else:
        flash("Correct the appointment details and try again.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="scheduling"))

@bp.post("/requests/<int:request_id>/link-customer")
@login_required
def link_customer_route(request_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.request_detail", request_id=request_id))

    form = LinkCustomerForm(prefix="link-customer")
    if form.validate_on_submit():
        try:
            link_quote_request_to_customer(request_id, int(form.customer_id.data))
            flash("Request linked to existing customer.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Select a valid customer before linking.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="customer-matching"))


@bp.post("/requests/<int:request_id>/create-customer")
@login_required
def create_customer_route(request_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.request_detail", request_id=request_id))

    form = CreateCustomerForm(prefix="create-customer")
    if form.validate_on_submit():
        try:
            create_customer_from_quote_request(request_id)
            flash("New customer record created and linked to the request.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Unable to create customer from request.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="customer-matching"))


@bp.get("/customers")
@login_required
def customer_list():
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    customers = list_customers()
    return render_template("admin/customers.html", customers=customers)


@bp.get("/recurring-work")
@login_required
def recurring_work_list():
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    works = list_recurring_works()
    return render_template("admin/recurring_work_list.html", recurring_works=works)


@bp.get("/recurring-work/<int:recurring_work_id>")
@login_required
def recurring_work_detail(recurring_work_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    work = get_recurring_work(recurring_work_id)
    return render_template("admin/recurring_work_detail.html", work=work)


@bp.get("/customers/<int:customer_id>")
@login_required
def customer_detail(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    customer = get_customer(customer_id)
    customer = get_customer(customer_id)
    billing_form = CustomerBillingForm(
        billing_amount=customer.billing_amount,
        billing_frequency=customer.billing_frequency,
        prefix="customer-billing",
    )
    add_field_form = CustomerFieldForm(prefix="add-customer-field")
    note_form = CustomerNoteForm(prefix="customer-note")
    set_primary_field_form = SetPrimaryFieldForm(prefix="set-primary")
    generate_recurring_appointments_form = RecurringWorkGenerationForm(prefix="generate-recurring")
    appointments = sorted(
        customer.appointments,
        key=lambda appointment: appointment.created_at,
        reverse=True,
    )
    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        billing_form=billing_form,
        add_field_form=add_field_form,
        note_form=note_form,
        set_primary_field_form=set_primary_field_form,
        generate_recurring_appointments_form=generate_recurring_appointments_form,
        appointments=appointments,
    )


@bp.get("/customers/<int:customer_id>/merge")
@login_required
def customer_merge(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    source = get_customer(customer_id)
    form = MergeCustomerForm(prefix="merge-customer")
    targets = [customer for customer in list_customers() if customer.id != source.id]
    form.target_customer_id.choices = [
        (target.id, f"{target.primary_name or 'Unnamed'} — {target.primary_email or 'no email'} — {target.primary_phone or 'no phone'}")
        for target in targets
    ]
    return render_template(
        "admin/customer_merge.html",
        source=source,
        targets=targets,
        merge_form=form,
    )


@bp.post("/customers/<int:customer_id>/merge")
@login_required
def customer_merge_action(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = MergeCustomerForm(prefix="merge-customer")
    targets = [customer for customer in list_customers() if customer.id != customer_id]
    form.target_customer_id.choices = [
        (target.id, f"{target.primary_name or 'Unnamed'} — {target.primary_email or 'no email'} — {target.primary_phone or 'no phone'}")
        for target in targets
    ]
    if form.validate_on_submit():
        try:
            merge_customers(customer_id, form.target_customer_id.data)
            flash("Customers merged successfully.", "success")
            return redirect(url_for("admin.customer_detail", customer_id=form.target_customer_id.data))
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Select a target customer and confirm the merge.", "error")

    source = get_customer(customer_id)
    return render_template(
        "admin/customer_merge.html",
        source=source,
        targets=targets,
        merge_form=form,
    )


@bp.post("/customers/<int:customer_id>/billing")
@login_required
def update_customer_billing_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = CustomerBillingForm(prefix="customer-billing")
    if form.validate_on_submit():
        try:
            update_customer_billing(customer_id, form.billing_amount.data, form.billing_frequency.data or None)
            flash("Customer billing updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Correct the billing information before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="billing"))


@bp.post("/customers/<int:customer_id>/fields")
@login_required
def add_customer_field_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = CustomerFieldForm(prefix="add-customer-field")
    if form.validate_on_submit():
        try:
            add_customer_field(customer_id, form.kind.data, form.value.data)
            flash("Customer field added.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Enter a valid value before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="fields"))


@bp.post("/customers/<int:customer_id>/set-primary")
@login_required
def set_primary_field_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = SetPrimaryFieldForm(prefix="set-primary")
    if form.validate_on_submit():
        try:
            set_primary_customer_field(customer_id, int(form.field_id.data))
            flash("Primary customer value updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Select a valid field before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="fields"))


@bp.post("/customers/<int:customer_id>/notes")
@login_required
def add_customer_note_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = CustomerNoteForm(prefix="customer-note")
    if form.validate_on_submit():
        try:
            add_customer_note(customer_id, form.note_text.data, current_user)
            flash("Customer note added.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Enter a note before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="notes"))

@bp.post("/customers/<int:customer_id>/recurring-work/generate")
@login_required
def generate_recurring_appointments_route(customer_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.customer_detail", customer_id=customer_id))

    form = RecurringWorkGenerationForm(prefix="generate-recurring")
    if form.validate_on_submit():
        try:
            days_ahead = int(form.days_ahead.data)
            created_count = generate_recurring_appointments_for_customer(customer_id, days_ahead=days_ahead)
            flash(
                f"Generated {created_count} upcoming recurring appointment{'s' if created_count != 1 else ''}.",
                "success",
            )
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Choose a valid generation window before running.", "error")

    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="appointments"))

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
        appointment = get_appointment(appointment_id)
        update_appointment(
            appointment_id,
            requested_date=form.requested_date.data,
            requested_time_window=(form.requested_time_window.data or "").strip() or None,
            confirmed_date=form.confirmed_date.data,
            confirmed_time_window=(form.confirmed_time_window.data or "").strip() or None,
            internal_notes=(form.internal_notes.data or appointment.internal_notes).strip() or None,
            scheduled_date=form.scheduled_date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            status=form.status.data,
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
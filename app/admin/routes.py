from calendar import month_name, monthcalendar, monthrange
from datetime import date, time, timedelta
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin import bp
from app.auth.routes import handle_admin_login
from app.forms.admin import (
    AppointmentForm,
    AppointmentStatusForm,
    CreateCustomerForm,
    CreateScheduledWorkForm,
    CustomerAddressForm,
    CustomerBillingForm,
    CustomerFieldForm,
    CustomerInfoForm,
    CustomerNoteForm,
    CustomerPhotoUploadForm,
    DeleteNoteForm,
    LastContactedForm,
    LinkCustomerForm,
    MergeCustomerForm,
    NoteForm,
    RecurringWorkGenerationForm,
    RecurringWorkForm,
    RequestQuoteDecisionForm,
    RequestQuoteForm,
    AppointmentStaffAssignmentForm,
    RescheduleAppointmentForm,
    SetPrimaryFieldForm,
    StaffAvailabilityForm,
    StaffMemberForm,
)
from app.models import APPOINTMENT_STATUSES
from app.services.admin_requests import (
    add_customer_field,
    add_customer_note,
    add_request_note,
    add_staff_availability,
    create_appointment,
    create_customer,
    create_request_quote,
    create_scheduled_work,
    create_recurring_work,
    create_customer_from_quote_request,
    create_staff_member,
    delete_request_note,
    delete_staff_availability,
    find_customer_matches_for_request,
    get_appointment,
    get_customer,
    get_quote_request,
    get_recurring_work,
    get_request_note,
    get_request_quote,
    get_staff_assignment_warnings,
    get_staff_member,
    generate_appointments_for_recurring_work,
    list_customers,
    list_quote_requests,
    list_recurring_works,
    list_staff_members,
    list_appointments_for_day,
    list_appointments_for_month,
    list_scheduled_appointments,
    set_appointment_staff_assignments,
    link_quote_request_to_customer,
    mark_quote_request_viewed,
    add_customer_address,
    generate_recurring_appointments_for_customer,
    link_quote_request_to_customer,
    merge_customers,
    reschedule_appointment,
    set_customer_billing_address,
    set_primary_customer_field,
    update_appointment,
    update_appointment_status,
    update_customer_billing,
    update_customer_info,
    update_recurring_work,
    update_request_quote_decision,
    update_staff_member,
    upload_customer_photos,
    update_last_contacted_on,
    update_request_note,
)


VALID_SCHEDULE_SOURCES = {"request", "customer", "calendar", "day"}
VALID_RECURRING_SOURCES = {"customer"}
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _calculate_scheduled_hours(
    appointments,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> float:
    minutes = 0
    for appointment in appointments:
        if appointment.status == "Cancelled" or not appointment.start_time or not appointment.end_time or not appointment.scheduled_date:
            continue
        if start_date and appointment.scheduled_date < start_date:
            continue
        if end_date and appointment.scheduled_date > end_date:
            continue
        minutes += (
            appointment.end_time.hour * 60 + appointment.end_time.minute
            - (appointment.start_time.hour * 60 + appointment.start_time.minute)
        )
    return minutes / 60


def _build_staff_schedule_url(staff_member_id: int, reference_date: date | None = None) -> str:
    target_date = reference_date or date.today()
    return url_for(
        "admin.calendar_view",
        year=target_date.year,
        month=target_date.month,
        view="list",
        show="upcoming",
        status="all",
        staff_id=staff_member_id,
        sort="soonest",
    )


def _summarize_availability_days(staff_member) -> tuple[list[int], str]:
    availability_days = sorted({window.day_of_week for window in staff_member.availability_windows})
    if not availability_days:
        return availability_days, "No weekly availability set"

    labels = [WEEKDAY_NAMES[index][:3] for index in availability_days[:3]]
    summary = ", ".join(labels)
    if len(availability_days) > 3:
        summary = f"{summary} +{len(availability_days) - 3} more"
    return availability_days, summary


def _build_schedule_source_args(
    *,
    source: str | None = None,
    request_id: int | None = None,
    customer_id: int | None = None,
    date_value: date | str | None = None,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    view: str | None = None,
    show: str | None = None,
    status: str | None = None,
    staff_id: int | None = None,
    sort_by: str | None = None,
) -> dict[str, object]:
    args: dict[str, object] = {}

    if source in VALID_SCHEDULE_SOURCES:
        args["source"] = source
    if request_id is not None:
        args["request_id"] = request_id
    if customer_id is not None:
        args["customer_id"] = customer_id
    if date_value is not None:
        args["date"] = date_value.isoformat() if isinstance(date_value, date) else date_value
    if year is not None:
        args["year"] = year
    if month is not None:
        args["month"] = month
    if day is not None:
        args["day"] = day
    if view in ("calendar", "list"):
        args["view"] = view
        if view == "list":
            args["show"] = show if show in ("upcoming", "all") else "upcoming"
            args["status"] = status or "all"
            args["staff_id"] = 0 if staff_id is None else staff_id
            args["sort"] = sort_by or "soonest"

    return args


def _schedule_source_args_from_request() -> dict[str, object]:
    return _build_schedule_source_args(
        source=request.args.get("source"),
        request_id=request.args.get("request_id", type=int),
        customer_id=request.args.get("customer_id", type=int),
        date_value=request.args.get("date"),
        year=request.args.get("year", type=int),
        month=request.args.get("month", type=int),
        day=request.args.get("day", type=int),
        view=request.args.get("view"),
        show=request.args.get("show"),
        status=request.args.get("status"),
        staff_id=request.args.get("staff_id", type=int),
        sort_by=request.args.get("sort"),
    )


def _resolve_schedule_return(
    *,
    source: str | None,
    quote_request=None,
    customer=None,
    scheduled_date: date | None = None,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    view: str | None = None,
    show: str | None = None,
    status: str | None = None,
    staff_id: int | None = None,
    sort_by: str | None = None,
) -> tuple[str, str]:
    if source == "request" and quote_request is not None:
        return url_for("admin.request_detail", request_id=quote_request.id), "Back to Request"

    if source == "customer" and customer is not None:
        return url_for("admin.customer_detail", customer_id=customer.id), "Back to Customer"

    context_date = scheduled_date
    if context_date is None and year is not None and month is not None and day is not None:
        try:
            context_date = date(year, month, day)
        except ValueError:
            context_date = None

    if source == "day" and context_date is not None:
        return (
            url_for(
                "admin.calendar_day_view",
                year=context_date.year,
                month=context_date.month,
                day=context_date.day,
            ),
            "Back to Day Agenda",
        )

    calendar_kwargs: dict[str, object] = {}
    if year is not None and month is not None:
        calendar_kwargs.update(year=year, month=month)
    if view in ("calendar", "list"):
        calendar_kwargs["view"] = view
        if view == "list":
            calendar_kwargs["show"] = show if show in ("upcoming", "all") else "upcoming"
            calendar_kwargs["status"] = status or "all"
            calendar_kwargs["staff_id"] = 0 if staff_id is None else staff_id
            calendar_kwargs["sort"] = sort_by or "soonest"

    return_label = "Back to Schedule"
    if view == "calendar":
        return_label = "Back to Calendar View"
    elif view == "list":
        return_label = "Back to List View"

    return url_for("admin.calendar_view", **calendar_kwargs), return_label


def _build_recurring_source_args(*, source: str | None = None, customer_id: int | None = None) -> dict[str, object]:
    args: dict[str, object] = {}
    if source in VALID_RECURRING_SOURCES and customer_id is not None:
        args["source"] = source
        args["customer_id"] = customer_id
    return args


def _recurring_source_args_from_request() -> dict[str, object]:
    return _build_recurring_source_args(
        source=request.args.get("source"),
        customer_id=request.args.get("customer_id", type=int),
    )


def _resolve_recurring_return(*, source: str | None, customer=None) -> tuple[str, str]:
    if source == "customer" and customer is not None:
        return (
            url_for("admin.customer_detail", customer_id=customer.id, _anchor="recurring-work"),
            "Back to Customer",
        )
    return url_for("admin.recurring_work_list"), "Back to Recurring Work"


def _validate_recurring_work_form(form: RecurringWorkForm) -> tuple[int | None, int | None, bool]:
    selected_day_of_week = form.day_of_week.data if form.day_of_week.data is not None and form.day_of_week.data >= 0 else None
    selected_day_of_month = form.day_of_month.data if form.day_of_month.data else None
    is_valid = True

    if form.frequency.data == "weekly":
        if selected_day_of_week is None:
            form.day_of_week.errors.append("Choose a weekday for weekly recurring work.")
            is_valid = False
        selected_day_of_month = None
    if form.frequency.data == "monthly":
        if selected_day_of_month is None:
            form.day_of_month.errors.append("Choose a day of month for monthly recurring work.")
            is_valid = False
        selected_day_of_week = None

    if form.ends_on.data and form.starts_on.data and form.ends_on.data < form.starts_on.data:
        form.ends_on.errors.append("End date must be on or after the start date.")
        is_valid = False
    start_time = form.time_value("start_time")
    end_time = form.time_value("end_time")
    if start_time and end_time and end_time <= start_time:
        form.end_time_hour.errors.append("Default end time must be after the default start time.")
        is_valid = False

    return selected_day_of_week, selected_day_of_month, is_valid


def _render_recurring_work_detail_page(
    *,
    work,
    recurring_work_form: RecurringWorkForm,
    generate_recurring_appointments_form: RecurringWorkGenerationForm,
    source_args: dict[str, object] | None = None,
):
    recurring_source_args = source_args or {}
    recurring_return_url, recurring_return_label = _resolve_recurring_return(
        source=recurring_source_args.get("source") if recurring_source_args else None,
        customer=work.customer,
    )
    generated_appointments = sorted(
        work.appointments,
        key=lambda appointment: (
            appointment.scheduled_date or date.max,
            appointment.start_time or time.min,
            appointment.id,
        ),
    )
    today_value = date.today()
    reference_date = next(
        (appointment.scheduled_date for appointment in generated_appointments if appointment.scheduled_date),
        work.starts_on or today_value,
    )
    recurring_calendar_url = None
    recurring_list_url = None
    if current_app.config.get("ENABLE_CALENDAR"):
        recurring_calendar_url = url_for(
            "admin.calendar_view",
            year=reference_date.year,
            month=reference_date.month,
            view="calendar",
        )
        recurring_list_url = url_for(
            "admin.calendar_view",
            year=reference_date.year,
            month=reference_date.month,
            view="list",
            show="upcoming",
            status="all",
            staff_id=0,
            sort="soonest",
        )

    return render_template(
        "admin/recurring_work_detail.html",
        work=work,
        recurring_work_form=recurring_work_form,
        generate_recurring_appointments_form=generate_recurring_appointments_form,
        generated_appointments=generated_appointments,
        generated_count=len(generated_appointments),
        upcoming_generated_count=sum(
            1
            for appointment in generated_appointments
            if appointment.scheduled_date and appointment.scheduled_date >= today_value and appointment.status != "Cancelled"
        ),
        recurring_return_url=recurring_return_url,
        recurring_return_label=recurring_return_label,
        recurring_calendar_url=recurring_calendar_url,
        recurring_list_url=recurring_list_url,
        edit_recurring_work_url=url_for("admin.edit_recurring_work_route", recurring_work_id=work.id, **recurring_source_args),
        generate_recurring_work_url=url_for("admin.generate_recurring_work_appointments_route", recurring_work_id=work.id, **recurring_source_args),
    )


@bp.route("", methods=["GET", "POST"])
def admin_entry():
    return handle_admin_login()


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
    view = request.args.get("view", "calendar")
    show = request.args.get("show", "upcoming")
    today = date.today()
    if view not in ("calendar", "list"):
        view = "calendar"
    if show not in ("upcoming", "all"):
        show = "upcoming"

    status = request.args.get("status", "all")
    staff_id = request.args.get("staff_id", type=int, default=0)
    sort_by = request.args.get("sort", "soonest")
    valid_sort_values = ("soonest", "latest", "customer", "status")
    if status not in ("all", *APPOINTMENT_STATUSES):
        status = "all"
    if staff_id is None:
        staff_id = 0
    if sort_by not in valid_sort_values:
        sort_by = "soonest"

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

    scheduled_appointments = []
    if view == "list":
        filter_status = None if status == "all" else status
        if show == "all":
            scheduled_appointments = list_scheduled_appointments(
                date(1900, 1, 1),
                date(9999, 12, 31),
                status=filter_status,
                staff_id=staff_id,
                sort_by=sort_by,
            )
        else:
            scheduled_appointments = list_scheduled_appointments(
                today,
                date(9999, 12, 31),
                status=filter_status,
                staff_id=staff_id,
                sort_by=sort_by,
            )

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
        view=view,
        show=show,
        status=status,
        staff_id=staff_id,
        sort_by=sort_by,
        sort_options=[
            ("soonest", "Soonest first"),
            ("latest", "Latest first"),
            ("customer", "Customer A-Z"),
            ("status", "Status"),
        ],
        statuses=APPOINTMENT_STATUSES,
        staff_members=list_staff_members(),
        scheduled_appointments=scheduled_appointments,
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


@bp.route("/scheduled-work/new", methods=["GET", "POST"])
@login_required
def new_scheduled_work():
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.dashboard"))

    request_id = request.args.get("request_id", type=int)
    customer_id = request.args.get("customer_id", type=int)
    date_str = request.args.get("date")
    source = request.args.get("source")
    if source not in VALID_SCHEDULE_SOURCES:
        source = None
    calendar_year = request.args.get("year", type=int)
    calendar_month = request.args.get("month", type=int)
    calendar_day = request.args.get("day", type=int)
    calendar_view = request.args.get("view", "calendar")
    if calendar_view not in ("calendar", "list"):
        calendar_view = "calendar"
    calendar_show = request.args.get("show", "upcoming")
    if calendar_show not in ("upcoming", "all"):
        calendar_show = "upcoming"
    calendar_status = request.args.get("status", "all")
    calendar_staff_id = request.args.get("staff_id", type=int)
    calendar_sort = request.args.get("sort", "soonest")

    quote_request = None
    customer = None
    scheduled_date = None

    if request_id is not None:
        try:
            quote_request = get_quote_request(request_id)
        except Exception:
            flash("Request not found.", "error")
            return redirect(url_for("admin.dashboard"))

    if customer_id is not None:
        try:
            customer = get_customer(customer_id)
        except Exception:
            flash("Customer not found.", "error")
            return redirect(url_for("admin.dashboard"))

    if date_str:
        try:
            scheduled_date = date.fromisoformat(date_str)
        except ValueError:
            flash("Invalid date format. Use YYYY-MM-DD.", "error")

    form = CreateScheduledWorkForm(prefix="scheduled-work")
    customers = list_customers()
    form.customer_id.choices = [
        (0, "Choose an existing customer"),
        *[
            (
                existing_customer.id,
                f"{existing_customer.primary_name or 'Unnamed'} — {existing_customer.primary_email or 'no email'} — {existing_customer.primary_phone or 'no phone'}",
            )
            for existing_customer in customers
        ],
    ]

    form_action_url = url_for(
        "admin.new_scheduled_work",
        **_build_schedule_source_args(
            source=source,
            request_id=request_id,
            customer_id=customer_id,
            date_value=date_str,
            year=calendar_year,
            month=calendar_month,
            day=calendar_day,
            view=calendar_view if source == "calendar" else None,
            show=calendar_show if source == "calendar" else None,
            status=calendar_status if source == "calendar" else None,
            staff_id=calendar_staff_id if source == "calendar" else None,
            sort_by=calendar_sort if source == "calendar" else None,
        ),
    )

    def render_scheduled_work_page():
        active_customer = customer or (quote_request.customer if quote_request and quote_request.customer else None)
        selected_context_date = form.scheduled_date.data or scheduled_date
        return_url, return_label = _resolve_schedule_return(
            source=source,
            quote_request=quote_request,
            customer=active_customer,
            scheduled_date=selected_context_date,
            year=calendar_year,
            month=calendar_month,
            day=calendar_day,
            view=calendar_view if source == "calendar" else None,
            show=calendar_show if source == "calendar" else None,
            status=calendar_status if source == "calendar" else None,
            staff_id=calendar_staff_id if source == "calendar" else None,
            sort_by=calendar_sort if source == "calendar" else None,
        )
        return render_template(
            "admin/scheduled_work_form.html",
            form=form,
            form_action_url=form_action_url,
            quote_request=quote_request,
            customer=active_customer,
            scheduled_date=selected_context_date,
            schedule_source=source,
            schedule_source_year=calendar_year,
            schedule_source_month=calendar_month,
            schedule_source_view=calendar_view,
            source_return_url=return_url,
            source_return_label=return_label,
        )

    if request.method == "GET":
        if quote_request:
            form.request_id.data = quote_request.id
            if quote_request.customer is not None:
                form.customer_id.data = quote_request.customer.id
            else:
                form.new_customer_name.data = quote_request.full_name
                form.new_customer_city.data = quote_request.city
            form.title.data = quote_request.service_list_display or quote_request.request_type
        if customer is not None:
            form.customer_id.data = customer.id
        if scheduled_date is not None:
            form.scheduled_date.data = scheduled_date

    if form.validate_on_submit():
        selected_customer_id = form.customer_id.data if form.customer_id.data else None
        if selected_customer_id == 0:
            selected_customer_id = None

        if selected_customer_id is None and not (form.new_customer_name.data or "").strip():
            form.customer_id.errors.append("Choose an existing customer or enter a new customer name.")
        if selected_customer_id is None and not (form.new_customer_city.data or "").strip():
            form.new_customer_city.errors.append("Enter a city for the new customer.")
        start_time = form.time_value("start_time")
        end_time = form.time_value("end_time")
        if start_time and end_time and end_time <= start_time:
            form.end_time_hour.errors.append("End time must be after the start time.")

        if form.errors:
            return render_scheduled_work_page()

        try:
            appointment = create_scheduled_work(
                request_id=int(form.request_id.data) if form.request_id.data else None,
                customer_id=selected_customer_id,
                new_customer_name=form.new_customer_name.data,
                new_customer_phone=form.new_customer_phone.data,
                new_customer_email=form.new_customer_email.data,
                new_customer_city=form.new_customer_city.data,
                title=form.title.data,
                scheduled_date=form.scheduled_date.data,
                start_time=start_time,
                end_time=end_time,
                status=form.status.data,
                customer_notes=form.customer_notes.data,
                internal_notes=form.internal_notes.data,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return render_scheduled_work_page()

        flash("Scheduled event created.", "success")
        active_customer = customer or appointment.customer or (quote_request.customer if quote_request and quote_request.customer else None)
        return redirect(
            url_for(
                "admin.appointment_detail",
                appointment_id=appointment.id,
                **_build_schedule_source_args(
                    source=source,
                    request_id=quote_request.id if source == "request" and quote_request else None,
                    customer_id=active_customer.id if source == "customer" and active_customer else None,
                    date_value=form.scheduled_date.data,
                    year=calendar_year,
                    month=calendar_month,
                    day=calendar_day or (form.scheduled_date.data.day if source == "day" and form.scheduled_date.data else None),
                    view=calendar_view if source == "calendar" else None,
                    show=calendar_show if source == "calendar" else None,
                    status=calendar_status if source == "calendar" else None,
                    staff_id=calendar_staff_id if source == "calendar" else None,
                    sort_by=calendar_sort if source == "calendar" else None,
                ),
            )
        )

    return render_scheduled_work_page()


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

    appointment_context_args = _schedule_source_args_from_request()
    appointment_return_url, appointment_return_label = _resolve_schedule_return(
        source=appointment_context_args.get("source") if appointment_context_args else None,
        quote_request=appointment.quote_request,
        customer=appointment.customer,
        scheduled_date=appointment.scheduled_date,
        year=appointment_context_args.get("year") if appointment_context_args else None,
        month=appointment_context_args.get("month") if appointment_context_args else None,
        day=appointment_context_args.get("day") if appointment_context_args else None,
        view=appointment_context_args.get("view") if appointment_context_args else None,
        show=appointment_context_args.get("show") if appointment_context_args else None,
        status=appointment_context_args.get("status") if appointment_context_args else None,
        staff_id=appointment_context_args.get("staff_id") if appointment_context_args else None,
        sort_by=appointment_context_args.get("sort") if appointment_context_args else None,
    )

    today_value = date.today()
    calendar_year = appointment.scheduled_date.year if appointment.scheduled_date else date.today().year
    calendar_month = appointment.scheduled_date.month if appointment.scheduled_date else date.today().month
    calendar_day = appointment.scheduled_date.day if appointment.scheduled_date else today_value.day

    list_show = appointment_context_args.get("show") if appointment_context_args else None
    if list_show not in ("upcoming", "all"):
        list_show = "upcoming"

    list_status = appointment_context_args.get("status") if appointment_context_args else None
    if list_status not in ("all", *APPOINTMENT_STATUSES):
        list_status = "all"

    list_staff_id = appointment_context_args.get("staff_id") if appointment_context_args else None
    if list_staff_id is None:
        list_staff_id = 0

    list_sort = appointment_context_args.get("sort") if appointment_context_args else None
    if list_sort not in ("soonest", "latest", "customer", "status"):
        list_sort = "soonest"

    appointment_calendar_url = url_for(
        "admin.calendar_view",
        year=calendar_year,
        month=calendar_month,
        view="calendar",
    )
    appointment_list_url = url_for(
        "admin.calendar_view",
        year=calendar_year,
        month=calendar_month,
        view="list",
        show=list_show,
        status=list_status,
        staff_id=list_staff_id,
        sort=list_sort,
    )
    appointment_day_url = url_for(
        "admin.calendar_day_view",
        year=calendar_year,
        month=calendar_month,
        day=calendar_day,
    )

    if current_app.config.get("ENABLE_SCHEDULING") and current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        assign_staff_form = AppointmentStaffAssignmentForm(
            prefix="assign-staff",
            staff_ids=[staff.id for staff in appointment.assigned_staff],
        )

        all_staff = list_staff_members()
        required_service_ids = {
            service.id
            for service in appointment.quote_request.services
        } if appointment.quote_request else set()
        required_service_names = [service.name for service in appointment.quote_request.services] if appointment.quote_request else []
        staff_assignment_info = []
        for staff in all_staff:
            warnings = get_staff_assignment_warnings(appointment, staff)
            can_cover_services = not required_service_ids or bool({service.id for service in staff.services} & required_service_ids)
            staff_info = {
                "staff": staff,
                "can_cover_services": can_cover_services,
                "service_names": [service.name for service in staff.services],
                "warnings": warnings,
                "warning_count": len(warnings),
                "is_assigned": any(assigned_staff.id == staff.id for assigned_staff in appointment.assigned_staff),
                "availability_summary": _summarize_availability_days(staff)[1],
                "schedule_url": _build_staff_schedule_url(staff.id, appointment.scheduled_date or today_value),
            }
            if required_service_names:
                staff_info["capability_label"] = "Can perform requested service" if can_cover_services else "No matching service listed"
            else:
                staff_info["capability_label"] = "Available for general assignment"
            staff_assignment_info.append(staff_info)

        staff_assignment_info.sort(
            key=lambda info: (
                not info["can_cover_services"],
                info["staff"].status != "active",
                info["warning_count"],
                info["staff"].display_name.lower(),
            )
        )
        matching_staff_info = [info for info in staff_assignment_info if info["can_cover_services"]]
        other_staff_info = [info for info in staff_assignment_info if not info["can_cover_services"]]
    else:
        assign_staff_form = None
        required_service_names = []
        matching_staff_info = []
        other_staff_info = []

    return render_template(
        "admin/appointment_detail.html",
        appointment=appointment,
        appointment_form=appointment_form,
        assign_staff_form=assign_staff_form,
        matching_staff_info=matching_staff_info,
        other_staff_info=other_staff_info,
        required_service_names=required_service_names,
        reschedule_form=reschedule_form,
        history=history,
        future_reschedules=future_reschedules,
        calendar_year=calendar_year,
        calendar_month=calendar_month,
        today=today_value,
        appointment_return_url=appointment_return_url,
        appointment_return_label=appointment_return_label,
        appointment_calendar_url=appointment_calendar_url,
        appointment_list_url=appointment_list_url,
        appointment_day_url=appointment_day_url,
        assign_staff_url=url_for("admin.assign_staff_to_appointment", appointment_id=appointment.id, **appointment_context_args),
        edit_appointment_url=url_for("admin.edit_appointment_route", appointment_id=appointment.id, **appointment_context_args),
        reschedule_appointment_url=url_for("admin.reschedule_appointment_route", appointment_id=appointment.id, **appointment_context_args),
    )


@bp.post("/appointments/<int:appointment_id>/assign-staff")
@login_required
def assign_staff_to_appointment(appointment_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))

    form = AppointmentStaffAssignmentForm(prefix="assign-staff")
    if form.validate_on_submit():
        try:
            set_appointment_staff_assignments(appointment_id, form.staff_ids.data)
            flash("Staff assignments updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Choose valid staff members before saving.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.appointment_detail", appointment_id=appointment.id, **_schedule_source_args_from_request()))


@bp.get("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    quote_request = mark_quote_request_viewed(request_id)
    note_form = NoteForm()
    request_quote_form = RequestQuoteForm(prefix="request-quote")
    quote_decision_forms = {
        quote.id: RequestQuoteDecisionForm(prefix=f"quote-decision-{quote.id}")
        for quote in quote_request.quotes
    }
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
    link_customer_form.manual_customer_id.choices = [
        (0, "Choose an existing customer"),
        *[
            (customer.id, f"{customer.primary_name or 'Unnamed'} — {customer.primary_email or 'no email'} — {customer.primary_phone or 'no phone'}")
            for customer in list_customers()
        ],
    ]
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
        note_form=note_form,
        request_quote_form=request_quote_form,
        quote_decision_forms=quote_decision_forms,
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


@bp.post("/requests/<int:request_id>/quotes")
@login_required
def create_request_quote_route(request_id: int):
    form = RequestQuoteForm(prefix="request-quote")
    if form.validate_on_submit():
        try:
            create_request_quote(request_id, form.amount.data, form.description.data)
            flash("Quote added.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Enter a valid quote amount before saving.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_id, _anchor="quotes"))


@bp.post("/quotes/<int:quote_id>/decision/<decision>")
@login_required
def update_request_quote_decision_route(quote_id: int, decision: str):
    request_quote = get_request_quote(quote_id)
    form = RequestQuoteDecisionForm(prefix=f"quote-decision-{quote_id}")
    if form.validate_on_submit():
        try:
            update_request_quote_decision(quote_id, decision)
            flash("Quote decision updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Invalid quote decision request.", "error")

    return redirect(url_for("admin.request_detail", request_id=request_quote.quote_request_id, _anchor="quotes"))

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
    if quote_request.customer:
        form.customer_id.choices = [
            (quote_request.customer.id, quote_request.customer.primary_name or 'Customer')
        ]
        form.customer_id.data = quote_request.customer.id
    else:
        form.customer_id.choices = [
            (customer.id, f"{customer.primary_name or 'Unnamed'} — {customer.primary_email or 'no email'} — {customer.primary_phone or 'no phone'}")
            for customer in list_customers()
        ]

    if form.validate_on_submit():
        if quote_request.customer_id is None and not form.customer_id.data:
            flash("Choose a customer or link the request before scheduling.", "error")
        elif not form.scheduled_date.data:
            flash("Enter a scheduled date before saving.", "error")
        else:
            if quote_request.customer_id is None and form.customer_id.data:
                link_quote_request_to_customer(request_id, int(form.customer_id.data))
            create_appointment(
                request_id,
                requested_date=form.requested_date.data,
                requested_time=form.time_value("requested_time"),
                customer_notes=(form.customer_notes.data or "").strip() or None,
                internal_notes=(form.internal_notes.data or "").strip() or None,
                confirmed_date=form.confirmed_date.data,
                confirmed_time=form.time_value("confirmed_time"),
                scheduled_date=form.scheduled_date.data,
                start_time=form.time_value("start_time"),
                end_time=form.time_value("end_time"),
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
    form.manual_customer_id.choices = [
        (0, "Choose an existing customer"),
        *[
            (customer.id, f"{customer.primary_name or 'Unnamed'} — {customer.primary_email or 'no email'} — {customer.primary_phone or 'no phone'}")
            for customer in list_customers()
        ],
    ]

    if form.validate_on_submit():
        selected_customer_id = None
        if form.customer_id.data:
            try:
                selected_customer_id = int(form.customer_id.data)
            except (TypeError, ValueError):
                selected_customer_id = None
        elif form.manual_customer_id.data:
            try:
                selected_customer_id = int(form.manual_customer_id.data)
            except (TypeError, ValueError):
                selected_customer_id = None

        if selected_customer_id:
            try:
                link_quote_request_to_customer(request_id, selected_customer_id)
                flash("Request linked to existing customer.", "success")
            except Exception as exc:
                flash(str(exc), "error")
        else:
            flash("Select an existing customer before linking.", "error")
    else:
        flash("Select an existing customer before linking.", "error")

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


@bp.get("/staff")
@login_required
def staff_list():
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    staff_members = sorted(
        list_staff_members(),
        key=lambda staff_member: (
            staff_member.status != "active",
            (staff_member.display_name or "").lower(),
        ),
    )
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    staff_rows = []
    for staff_member in staff_members:
        assigned_appointments = sorted(
            [appt for appt in staff_member.assigned_appointments if appt.scheduled_date is not None and appt.status != "Cancelled"],
            key=lambda appt: (
                appt.scheduled_date,
                appt.start_time.strftime('%H:%M') if appt.start_time else "",
                appt.id,
            ),
        )
        upcoming_assignments = [appt for appt in assigned_appointments if appt.scheduled_date >= today]
        next_assignment = upcoming_assignments[0] if upcoming_assignments else None
        availability_days, availability_summary = _summarize_availability_days(staff_member)
        schedule_reference_date = next_assignment.scheduled_date if next_assignment and next_assignment.scheduled_date else today
        staff_rows.append(
            {
                "staff_member": staff_member,
                "upcoming_count": len(upcoming_assignments),
                "next_assignment": next_assignment,
                "availability_days_count": len(availability_days),
                "availability_summary": availability_summary,
                "availability_window_count": len(staff_member.availability_windows),
                "current_week_hours": _calculate_scheduled_hours(assigned_appointments, start_date=week_start, end_date=week_end),
                "current_month_hours": _calculate_scheduled_hours(assigned_appointments, start_date=month_start, end_date=month_end),
                "schedule_url": _build_staff_schedule_url(staff_member.id, schedule_reference_date),
            }
        )
    return render_template("admin/staff_list.html", staff_rows=staff_rows)


@bp.route("/staff/new", methods=["GET", "POST"])
@login_required
def new_staff_member():
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    form = StaffMemberForm(prefix="staff")
    if request.method == "POST" and form.validate_on_submit():
        try:
            staff_member = create_staff_member(
                display_name=form.display_name.data,
                phone=form.phone.data,
                email=form.email.data,
                role_title=form.role_title.data,
                worker_type=form.worker_type.data,
                status=form.status.data,
                notes=form.notes.data,
                service_ids=form.services.data,
            )
            flash("Staff member created.", "success")
            return redirect(url_for("admin.staff_detail", staff_member_id=staff_member.id))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("admin/staff_form.html", form=form, is_new=True)


@bp.get("/staff/<int:staff_member_id>")
@login_required
def staff_detail(staff_member_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    staff_member = get_staff_member(staff_member_id)
    today = date.today()
    assigned_appointments = sorted(
        [appt for appt in staff_member.assigned_appointments if appt.scheduled_date is not None and appt.status != "Cancelled"],
        key=lambda appt: (
            appt.scheduled_date,
            appt.start_time.strftime('%H:%M') if appt.start_time else "",
            appt.id,
        ),
    )
    upcoming_assignments = [
        appt for appt in assigned_appointments
        if appt.scheduled_date >= today and appt.status != "Cancelled"
    ]
    recent_completed = [
        appt for appt in assigned_appointments
        if appt.status == "Completed" and appt.scheduled_date <= today
    ]
    recent_completed.sort(
        key=lambda appt: (
            appt.scheduled_date,
            appt.start_time.strftime('%H:%M') if appt.start_time else "",
            appt.id,
        ),
        reverse=True,
    )

    filter_start = request.args.get("start_date")
    filter_end = request.args.get("end_date")
    start_date = None
    end_date = None
    custom_hours = None
    if filter_start:
        try:
            start_date = date.fromisoformat(filter_start)
        except ValueError:
            start_date = None
    if filter_end:
        try:
            end_date = date.fromisoformat(filter_end)
        except ValueError:
            end_date = None

    scheduled_hours = _calculate_scheduled_hours(assigned_appointments)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    current_week_hours = _calculate_scheduled_hours(assigned_appointments, start_date=week_start, end_date=week_end)
    month_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    current_month_hours = _calculate_scheduled_hours(assigned_appointments, start_date=month_start, end_date=month_end)
    if start_date is not None or end_date is not None:
        custom_hours = _calculate_scheduled_hours(assigned_appointments, start_date=start_date, end_date=end_date)

    availability_form = StaffAvailabilityForm(prefix="availability")
    availability_by_day = []
    for index, day_name in enumerate(WEEKDAY_NAMES):
        windows = [window for window in staff_member.availability_windows if window.day_of_week == index]
        if windows:
            availability_by_day.append({"day_name": day_name, "windows": windows})

    schedule_reference_date = upcoming_assignments[0].scheduled_date if upcoming_assignments else today
    return render_template(
        "admin/staff_detail.html",
        staff_member=staff_member,
        availability_form=availability_form,
        availability_by_day=availability_by_day,
        upcoming_assignments=upcoming_assignments,
        recent_completed=recent_completed,
        scheduled_hours=scheduled_hours,
        current_week_hours=current_week_hours,
        current_month_hours=current_month_hours,
        custom_hours=custom_hours,
        filter_start=filter_start,
        filter_end=filter_end,
        today=today,
        weekday_names=WEEKDAY_NAMES,
        upcoming_assignment_count=len(upcoming_assignments),
        service_count=len(staff_member.services),
        availability_day_count=len(availability_by_day),
        availability_window_count=len(staff_member.availability_windows),
        upcoming_scheduled_hours=_calculate_scheduled_hours(upcoming_assignments),
        staff_schedule_url=_build_staff_schedule_url(staff_member.id, schedule_reference_date),
    )


@bp.route("/staff/<int:staff_member_id>/edit", methods=["GET", "POST"])
@login_required
def edit_staff_member(staff_member_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    staff_member = get_staff_member(staff_member_id)
    form = StaffMemberForm(
        prefix="staff",
        display_name=staff_member.display_name,
        phone=staff_member.phone,
        email=staff_member.email,
        role_title=staff_member.role_title,
        worker_type=staff_member.worker_type,
        status=staff_member.status,
        services=[service.id for service in staff_member.services],
        notes=staff_member.notes,
    )
    if request.method == "POST" and form.validate_on_submit():
        try:
            update_staff_member(
                staff_member_id=staff_member.id,
                display_name=form.display_name.data,
                phone=form.phone.data,
                email=form.email.data,
                role_title=form.role_title.data,
                worker_type=form.worker_type.data,
                status=form.status.data,
                notes=form.notes.data,
                service_ids=form.services.data,
            )
            flash("Staff member updated.", "success")
            return redirect(url_for("admin.staff_detail", staff_member_id=staff_member.id))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("admin/staff_form.html", form=form, is_new=False, staff_member=staff_member)


@bp.post("/staff/<int:staff_member_id>/availability")
@login_required
def add_staff_availability_route(staff_member_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    form = StaffAvailabilityForm(prefix="availability")
    if form.validate_on_submit():
        try:
            add_staff_availability(
                staff_member_id=staff_member_id,
                day_of_week=form.day_of_week.data,
                start_time=form.time_value("start_time"),
                end_time=form.time_value("end_time"),
                notes=form.notes.data,
            )
            flash("Availability added.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Correct the availability details before saving.", "error")
    return redirect(url_for("admin.staff_detail", staff_member_id=staff_member_id, _anchor="availability"))


@bp.post("/staff/<int:staff_member_id>/availability/<int:availability_id>/delete")
@login_required
def delete_staff_availability_route(staff_member_id: int, availability_id: int):
    if not current_app.config.get("ENABLE_SCHEDULING") or not current_app.config.get("ENABLE_STAFF_MANAGEMENT"):
        return redirect(url_for("admin.dashboard"))
    try:
        delete_staff_availability(availability_id)
        flash("Availability removed.", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.staff_detail", staff_member_id=staff_member_id, _anchor="availability"))


@bp.get("/recurring-work")
@login_required
def recurring_work_list():
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    works = sorted(
        list_recurring_works(),
        key=lambda work: (
            work.status != "active",
            (work.customer.primary_name or "").lower() if work.customer else "",
            (work.title or "").lower(),
            work.starts_on or date.max,
            work.id,
        ),
    )
    return render_template("admin/recurring_work_list.html", recurring_works=works)


@bp.route("/customers/<int:customer_id>/recurring-work/new", methods=["GET", "POST"])
@login_required
def new_recurring_work(customer_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))

    customer = get_customer(customer_id)
    form = RecurringWorkForm(prefix="recurring-work")

    if request.method == "GET":
        if form.frequency.data is None:
            form.frequency.data = "weekly"
        if form.status.data is None:
            form.status.data = "active"
        if form.starts_on.data is None:
            form.starts_on.data = date.today()

    if form.validate_on_submit():
        selected_day_of_week, selected_day_of_month, has_valid_schedule = _validate_recurring_work_form(form)
        if has_valid_schedule:
            try:
                work = create_recurring_work(
                    customer.id,
                    title=form.title.data,
                    frequency=form.frequency.data,
                    day_of_week=selected_day_of_week,
                    day_of_month=selected_day_of_month,
                    starts_on=form.starts_on.data,
                    ends_on=form.ends_on.data,
                    start_time=form.time_value("start_time"),
                    end_time=form.time_value("end_time"),
                    status=form.status.data,
                    notes=form.notes.data,
                )
                flash("Recurring work saved.", "success")
                return redirect(
                    url_for(
                        "admin.recurring_work_detail",
                        recurring_work_id=work.id,
                        **_build_recurring_source_args(source="customer", customer_id=customer.id),
                    )
                )
            except Exception as exc:
                flash(str(exc), "error")

    return render_template(
        "admin/recurring_work_form.html",
        customer=customer,
        form=form,
        source_return_url=url_for("admin.customer_detail", customer_id=customer.id, _anchor="recurring-work"),
        source_return_label="Back to Customer",
    )


@bp.get("/recurring-work/<int:recurring_work_id>")
@login_required
def recurring_work_detail(recurring_work_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    work = get_recurring_work(recurring_work_id)
    recurring_work_form = RecurringWorkForm(prefix="recurring-work", obj=work)
    if recurring_work_form.day_of_week.data is None:
        recurring_work_form.day_of_week.data = -1
    if recurring_work_form.day_of_month.data is None:
        recurring_work_form.day_of_month.data = 0
    generate_recurring_appointments_form = RecurringWorkGenerationForm(prefix="generate-recurring")
    return _render_recurring_work_detail_page(
        work=work,
        recurring_work_form=recurring_work_form,
        generate_recurring_appointments_form=generate_recurring_appointments_form,
        source_args=_recurring_source_args_from_request(),
    )


@bp.post("/recurring-work/<int:recurring_work_id>/edit")
@login_required
def edit_recurring_work_route(recurring_work_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))

    work = get_recurring_work(recurring_work_id)
    recurring_work_form = RecurringWorkForm(prefix="recurring-work")
    generate_recurring_appointments_form = RecurringWorkGenerationForm(prefix="generate-recurring")
    recurring_source_args = _recurring_source_args_from_request()

    if recurring_work_form.validate_on_submit():
        selected_day_of_week, selected_day_of_month, has_valid_schedule = _validate_recurring_work_form(recurring_work_form)
        if has_valid_schedule:
            try:
                update_recurring_work(
                    recurring_work_id,
                    title=recurring_work_form.title.data,
                    frequency=recurring_work_form.frequency.data,
                    day_of_week=selected_day_of_week,
                    day_of_month=selected_day_of_month,
                    starts_on=recurring_work_form.starts_on.data,
                    ends_on=recurring_work_form.ends_on.data,
                    start_time=recurring_work_form.time_value("start_time"),
                    end_time=recurring_work_form.time_value("end_time"),
                    status=recurring_work_form.status.data,
                    notes=recurring_work_form.notes.data,
                )
                flash("Recurring work updated.", "success")
                return redirect(url_for("admin.recurring_work_detail", recurring_work_id=recurring_work_id, **recurring_source_args))
            except Exception as exc:
                flash(str(exc), "error")

    return _render_recurring_work_detail_page(
        work=work,
        recurring_work_form=recurring_work_form,
        generate_recurring_appointments_form=generate_recurring_appointments_form,
        source_args=recurring_source_args,
    )


@bp.post("/recurring-work/<int:recurring_work_id>/generate")
@login_required
def generate_recurring_work_appointments_route(recurring_work_id: int):
    if not current_app.config.get("ENABLE_RECURRING_WORK"):
        return redirect(url_for("admin.dashboard"))
    if not current_app.config.get("ENABLE_SCHEDULING"):
        return redirect(url_for("admin.recurring_work_detail", recurring_work_id=recurring_work_id, **_recurring_source_args_from_request()))

    work = get_recurring_work(recurring_work_id)
    form = RecurringWorkGenerationForm(prefix="generate-recurring")
    recurring_source_args = _recurring_source_args_from_request()
    if form.validate_on_submit():
        try:
            created_count = generate_appointments_for_recurring_work(recurring_work_id, days_ahead=int(form.days_ahead.data))
            if created_count:
                flash(
                    f"Generated {created_count} upcoming appointment{'s' if created_count != 1 else ''} for {work.title or 'this recurring work'}.",
                    "success",
                )
            else:
                flash("No upcoming appointments were generated. This recurring plan may already be up to date or inactive.", "warning")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Choose a valid generation window before running.", "error")

    return redirect(
        url_for(
            "admin.recurring_work_detail",
            recurring_work_id=recurring_work_id,
            _anchor="generated-appointments",
            **recurring_source_args,
        )
    )


@bp.get("/customers/<int:customer_id>")
@login_required
def customer_detail(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    customer = get_customer(customer_id)
    billing_form = CustomerBillingForm(
        billing_amount=customer.billing_amount,
        billing_frequency=customer.billing_frequency,
        prefix="customer-billing",
    )
    customer_info_form = CustomerInfoForm(
        prefix="customer-info",
        primary_name=customer.primary_name,
        primary_phone=customer.primary_phone,
        primary_email=customer.primary_email,
        primary_city=customer.primary_city,
    )
    address_form = CustomerAddressForm(prefix="customer-address")
    photo_upload_form = CustomerPhotoUploadForm(prefix="customer-photos")
    add_field_form = CustomerFieldForm(prefix="add-customer-field")
    note_form = CustomerNoteForm(prefix="customer-note")
    set_primary_field_form = SetPrimaryFieldForm(prefix="set-primary")
    generate_recurring_appointments_form = RecurringWorkGenerationForm(prefix="generate-recurring")
    appointments = sorted(
        customer.appointments,
        key=lambda appointment: (
            appointment.scheduled_date or date.min,
            appointment.start_time or time.min,
            appointment.created_at,
        ),
        reverse=True,
    )
    request_history = sorted(
        customer.quote_requests,
        key=lambda quote_request: quote_request.created_at,
        reverse=True,
    )
    customer_notes = sorted(
        customer.notes,
        key=lambda note: note.created_at,
        reverse=True,
    )
    recurring_works = sorted(
        customer.recurring_works,
        key=lambda work: (work.starts_on or date.min, work.id),
        reverse=True,
    )
    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        billing_form=billing_form,
        customer_info_form=customer_info_form,
        address_form=address_form,
        photo_upload_form=photo_upload_form,
        add_field_form=add_field_form,
        note_form=note_form,
        set_primary_field_form=set_primary_field_form,
        generate_recurring_appointments_form=generate_recurring_appointments_form,
        request_history=request_history,
        customer_notes=customer_notes,
        recurring_works=recurring_works,
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


@bp.post("/customers/<int:customer_id>/info")
@login_required
def update_customer_info_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = CustomerInfoForm(prefix="customer-info")
    if form.validate_on_submit():
        try:
            update_customer_info(
                customer_id,
                form.primary_name.data,
                form.primary_phone.data,
                form.primary_email.data,
                form.primary_city.data,
            )
            flash("Customer details updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Correct the customer details before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="customer-info"))


@bp.post("/customers/<int:customer_id>/addresses")
@login_required
def add_customer_address_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))

    form = CustomerAddressForm(prefix="customer-address")
    if form.validate_on_submit():
        try:
            add_customer_address(
                customer_id,
                form.address_line_1.data,
                form.address_line_2.data,
                form.state.data,
                form.zip_code.data,
                form.is_billing.data,
            )
            flash("Customer address added.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Correct the address details before saving.", "error")

    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="customer-addresses"))


@bp.post("/customers/<int:customer_id>/addresses/<int:address_id>/billing")
@login_required
def set_customer_billing_address_route(customer_id: int, address_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))

    try:
        set_customer_billing_address(customer_id, address_id)
        flash("Billing address updated.", "success")
    except Exception as exc:
        flash(str(exc), "error")

    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="customer-addresses"))


@bp.post("/customers/<int:customer_id>/photos")
@login_required
def upload_customer_photos_route(customer_id: int):
    if not current_app.config.get("ENABLE_CUSTOMER_RECORDS"):
        return redirect(url_for("admin.dashboard"))
    form = CustomerPhotoUploadForm(prefix="customer-photos")
    if form.validate_on_submit():
        try:
            files = request.files.getlist("customer-photos-photos")
            upload_customer_photos(customer_id, files)
            flash("Customer photos uploaded.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    else:
        flash("Upload valid image files before saving.", "error")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id, _anchor="gallery"))


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
    return redirect(url_for("admin.appointment_detail", appointment_id=appointment.id, **_schedule_source_args_from_request()))


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
            title=(form.title.data or "").strip() or None,
            requested_date=form.requested_date.data,
            requested_time=form.time_value("requested_time"),
            confirmed_date=form.confirmed_date.data,
            confirmed_time=form.time_value("confirmed_time"),
            customer_notes=(form.customer_notes.data or "").strip() or None,
            internal_notes=(form.internal_notes.data or "").strip() or None,
            scheduled_date=form.scheduled_date.data,
            start_time=form.time_value("start_time"),
            end_time=form.time_value("end_time"),
            status=form.status.data,
        )
        flash("Appointment details updated.", "success")
    else:
        flash("Correct the appointment details and try again.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.appointment_detail", appointment_id=appointment.id, **_schedule_source_args_from_request()))


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
                requested_time=form.time_value("requested_time"),
                internal_notes=(form.internal_notes.data or "").strip() or None,
            )
            flash("Appointment rescheduled.", "success")
    else:
        flash("Correct the reschedule details and try again.", "error")

    appointment = get_appointment(appointment_id)
    return redirect(url_for("admin.appointment_detail", appointment_id=appointment.id, **_schedule_source_args_from_request()))


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
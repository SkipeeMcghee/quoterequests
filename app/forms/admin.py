from app.models import APPOINTMENT_STATUSES, RecurringWork, RequestQuote, ServiceOption, StaffMember
from app.services.service_catalog import is_services_enabled, list_service_id_choices
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired, MultipleFileField
from wtforms import BooleanField, DateField, DecimalField, HiddenField, IntegerField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, NumberRange, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.forms.time_selects import TimeSelectMixin


class CheckboxInputWithoutRequired(CheckboxInput):
    validation_attrs = ["disabled"]


def _load_service_choices() -> list[tuple[int, str]]:
    return list_service_id_choices(include_inactive=False)


def _load_service_choices_with_selected(selected_ids: list[int] | None = None) -> list[tuple[int, str]]:
    return list_service_id_choices(include_inactive=False, selected_ids=selected_ids)


def _load_staff_choices() -> list[tuple[int, str]]:
    from app.models import StaffMember

    staff_members = StaffMember.query.order_by(StaffMember.display_name).all()
    return [(staff.id, staff.display_name) for staff in staff_members]


def _load_gallery_service_choices() -> list[tuple[int, str]]:
    services = ServiceOption.query.order_by(ServiceOption.display_order.asc(), ServiceOption.name.asc()).all()
    choices = [(0, "No linked service")]
    for service in services:
        label = service.name if service.is_active else f"{service.name} (inactive)"
        choices.append((service.id, label))
    return choices


def _load_recurring_work_service_choices(selected_title: str | None = None) -> list[tuple[str, str]]:
    cleaned_selected_title = (selected_title or "").strip()
    choices: list[tuple[str, str]] = []
    known_titles: set[str] = set()

    for service in ServiceOption.ordered_query(include_inactive=True).all():
        known_titles.add(service.name)
        label = service.name if service.is_active else f"{service.name} (inactive)"
        choices.append((service.name, label))

    if cleaned_selected_title and cleaned_selected_title not in known_titles:
        choices.insert(0, (cleaned_selected_title, f"{cleaned_selected_title} (legacy)"))

    return choices


def _resolve_recurring_work_service_ids_for_title(title: str | None = None) -> list[int]:
    cleaned_titles = [service_name.strip() for service_name in (title or "").split(",") if service_name.strip()]
    if not cleaned_titles:
        return []

    services = ServiceOption.query.filter(ServiceOption.name.in_(cleaned_titles)).order_by(ServiceOption.display_order.asc(), ServiceOption.name.asc()).all()
    return [service.id for service in services]


def _normalize_weekday_selection(raw_values) -> list[int]:
    if raw_values in (None, ""):
        return []

    if isinstance(raw_values, (int, str)):
        raw_iterable = [raw_values]
    else:
        raw_iterable = list(raw_values)

    normalized: list[int] = []
    seen_values: set[int] = set()
    for raw_value in raw_iterable:
        try:
            weekday = int(raw_value)
        except (TypeError, ValueError):
            continue

        if weekday < 0 or weekday > 6 or weekday in seen_values:
            continue

        seen_values.add(weekday)
        normalized.append(weekday)

    return sorted(normalized)


def _normalize_month_day_selection(raw_values) -> list[int]:
    if raw_values in (None, ""):
        return []

    if isinstance(raw_values, (int, str)):
        raw_iterable = [raw_values]
    else:
        raw_iterable = list(raw_values)

    normalized: list[int] = []
    seen_values: set[int] = set()
    for raw_value in raw_iterable:
        try:
            month_day = int(raw_value)
        except (TypeError, ValueError):
            continue

        if month_day < 1 or month_day > 31 or month_day in seen_values:
            continue

        seen_values.add(month_day)
        normalized.append(month_day)

    return sorted(normalized)


def _resolve_recurring_work_form_schedule_defaults(source) -> dict[str, object]:
    if source is None:
        return {
            "frequency": "weekly",
            "unit": "week",
            "interval": 1,
            "weekdays": [],
            "month_days": [],
        }

    raw_config = getattr(source, "recurrence_config", None) or {}
    frequency = getattr(source, "frequency", None) or "weekly"

    unit = str(raw_config.get("unit") or "").strip().lower()
    if unit not in {"week", "month"}:
        unit = "month" if frequency in {"monthly", "semi_monthly", "bimonthly"} else "week"

    try:
        interval = int(raw_config.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 1
    if interval < 1:
        interval = 1

    weekdays = _normalize_weekday_selection(raw_config.get("weekdays"))
    month_days = _normalize_month_day_selection(raw_config.get("month_days"))

    if unit == "week" and not weekdays and getattr(source, "day_of_week", None) is not None:
        weekdays = [int(source.day_of_week)]
    if unit == "month" and not month_days and getattr(source, "day_of_month", None) is not None:
        month_days = [int(source.day_of_month)]

    return {
        "frequency": frequency,
        "unit": unit,
        "interval": interval,
        "weekdays": weekdays,
        "month_days": month_days,
    }


class RequestQuoteForm(FlaskForm):
    amount = DecimalField(
        "Quote amount",
        places=2,
        validators=[DataRequired(), NumberRange(min=0)],
        render_kw={"step": "0.01", "min": "0"},
    )
    billing_frequency = SelectField(
        "Billing frequency",
        choices=[(frequency, frequency) for frequency in RequestQuote.BILLING_FREQUENCIES],
        default="Monthly",
        validators=[DataRequired()],
    )
    description = StringField("Quote details", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Add Quote")


class RequestQuoteDecisionForm(FlaskForm):
    decision = SelectField(
        "Status",
        choices=[(decision, decision) for decision in RequestQuote.DECISIONS],
        default="Sent",
        validators=[DataRequired()],
    )
    submit = SubmitField("Save Decision")


class ActionForm(FlaskForm):
    pass


class NoteForm(FlaskForm):
    note_text = TextAreaField("Internal note", validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField("Save Changes")


class DeleteNoteForm(FlaskForm):
    submit = SubmitField("Delete")


class LastContactedForm(FlaskForm):
    last_contacted_on = DateField("Last contacted on", validators=[Optional()])
    submit = SubmitField("Save Last Contact")


class LinkCustomerForm(FlaskForm):
    customer_id = HiddenField("Customer ID", validators=[Optional()])
    manual_customer_lookup = StringField("Customer", validators=[Optional()])
    manual_customer_id = HiddenField("Customer", validators=[Optional()])
    submit = SubmitField("Link Customer")


class CreateCustomerForm(FlaskForm):
    submit = SubmitField("Add Customer")


class CustomerInfoForm(FlaskForm):
    individual_name = StringField("Individual name", validators=[Optional(), Length(max=255)])
    business_name = StringField("Business name", validators=[Optional(), Length(max=255)])
    display_name_preference = SelectField("Display name", choices=[("individual", "Individual name")], validators=[Optional()])
    primary_phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    primary_email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    primary_city = StringField("City", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save Customer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.display_name_preference.validate_choice = False
        self.set_display_name_choices(self.individual_name.data, self.business_name.data)

    def set_display_name_choices(self, individual_name: str | None, business_name: str | None) -> None:
        choices = []
        if (individual_name or "").strip():
            choices.append(("individual", "Individual name"))
        if (business_name or "").strip():
            choices.append(("business", "Business name"))
        if not choices:
            choices = [("individual", "Individual name")]
        self.display_name_preference.choices = choices
        available = {value for value, _label in choices}
        if self.display_name_preference.data not in available:
            self.display_name_preference.data = choices[0][0]

    def validate(self, extra_validators=None):
        self.set_display_name_choices(self.individual_name.data, self.business_name.data)
        valid = super().validate(extra_validators=extra_validators)
        has_individual = bool((self.individual_name.data or "").strip())
        has_business = bool((self.business_name.data or "").strip())

        if not (has_individual or has_business):
            self.individual_name.errors.append("Enter an individual name or a business name.")
            valid = False

        selected_name = (self.display_name_preference.data or "").strip()
        if selected_name == "business" and not has_business:
            self.display_name_preference.errors.append("Add a business name before using it as the display name.")
            valid = False
        if selected_name == "individual" and not has_individual:
            self.display_name_preference.errors.append("Add an individual name before using it as the display name.")
            valid = False

        return valid


class CustomerAddressForm(FlaskForm):
    address_line_1 = StringField("Address Line 1", validators=[Optional(), Length(max=255)])
    address_line_2 = StringField("Address Line 2", validators=[Optional(), Length(max=255)])
    state = StringField("State", validators=[Optional(), Length(max=255)])
    zip_code = StringField("Zip", validators=[Optional(), Length(max=20)])
    is_billing = BooleanField("Mark as billing address", validators=[Optional()])
    submit = SubmitField("Add Address")


class CustomerPhotoUploadForm(FlaskForm):
    photos = MultipleFileField(
        "Customer photos",
        validators=[FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")],
    )
    submit = SubmitField("Upload Photos")


class CustomerFieldForm(FlaskForm):
    kind = SelectField(
        "Field type",
        choices=[("name", "Name"), ("phone", "Phone"), ("email", "Email"), ("city", "City")],
        validators=[DataRequired()],
    )
    value = StringField("Value", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Add Contact Detail")


class SetPrimaryFieldForm(FlaskForm):
    field_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Set Primary")


class CustomerBillingForm(FlaskForm):
    billing_amount = DecimalField(
        "Billing amount",
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"step": "0.01"},
    )
    billing_frequency = SelectField(
        "Billing frequency",
        choices=[("", "None"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("per_job", "Per job")],
        validators=[Optional()],
    )
    submit = SubmitField("Save Billing")


class CustomerNoteForm(FlaskForm):
    note_text = TextAreaField("Customer note", validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField("Add Note")


class MergeCustomerForm(FlaskForm):
    target_customer_id = SelectField("Surviving customer", coerce=int, validators=[DataRequired()])
    confirm = BooleanField("I understand this will merge the source customer into the selected target", validators=[DataRequired()])
    submit = SubmitField("Merge Customer")


class StaffMemberForm(FlaskForm):
    display_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    worker_type = SelectField(
        "Worker type",
        choices=[("employee", "Employee"), ("contractor", "Contractor")],
        validators=[DataRequired()],
    )
    status = SelectField(
        "Status",
        choices=[("active", "Active"), ("inactive", "Inactive")],
        validators=[DataRequired()],
    )
    compensation_amount = DecimalField(
        "Compensation amount",
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"step": "0.01", "min": "0", "inputmode": "decimal"},
    )
    compensation_frequency = SelectField(
        "Compensation frequency",
        choices=[("", "Choose frequency"), *StaffMember.COMPENSATION_FREQUENCY_CHOICES],
        validators=[Optional()],
    )
    services = SelectMultipleField(
        "Services",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    notes = TextAreaField("Staff Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services_enabled = is_services_enabled()
        self.set_service_choices(selected_ids=self.services.data)

    def set_service_choices(self, selected_ids: list[int] | None = None) -> None:
        self.services.validate_choice = False
        if not self.services_enabled:
            self.services.choices = []
            return
        self.services.choices = _load_service_choices_with_selected(selected_ids)

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        has_amount = self.compensation_amount.data not in (None, "")
        has_frequency = bool((self.compensation_frequency.data or "").strip())

        if has_amount and not has_frequency:
            self.compensation_frequency.errors.append("Choose a compensation frequency.")
            valid = False
        if has_frequency and not has_amount:
            self.compensation_amount.errors.append("Enter a compensation amount.")
            valid = False

        return valid


class StaffNotesForm(FlaskForm):
    notes = TextAreaField("Staff Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Staff Notes")


class AppointmentStaffAssignmentForm(FlaskForm):
    staff_ids = SelectMultipleField(
        "Assigned staff",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    submit = SubmitField("Save Staff Assignment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_ids.choices = _load_staff_choices()


class StaffAvailabilityForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "start_time": {"label": "start time", "required": True},
        "end_time": {"label": "end time", "required": True},
    }

    day_of_week = SelectField(
        "Day of week",
        choices=[(str(i), day) for i, day in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])],
        coerce=int,
        validators=[InputRequired()],
    )
    start_time_hour = SelectField("Start time hour", validators=[Optional()])
    start_time_minute = SelectField("Start time minute", validators=[Optional()])
    end_time_hour = SelectField("End time hour", validators=[Optional()])
    end_time_minute = SelectField("End time minute", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initialize_time_selects()

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        return self.validate_time_selects() and valid


class StaffAvailabilitySyncForm(FlaskForm):
    windows_json = HiddenField(validators=[DataRequired()])


class CreateScheduledWorkForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "start_time": {"label": "start time", "required": True},
        "end_time": {"label": "end time", "required": True},
    }

    request_id = HiddenField()
    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    customer_lookup = StringField("Customer", validators=[Optional()])
    new_customer_name = StringField("New customer name", validators=[Optional(), Length(max=255)])
    new_customer_phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    new_customer_email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    new_customer_city = StringField("City", validators=[Optional(), Length(max=255)])
    title = StringField("Work title / summary", validators=[DataRequired(), Length(max=255)])
    service_ids = SelectMultipleField(
        "Services",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    scheduled_date = DateField("Scheduled date", validators=[DataRequired()])
    start_time_hour = SelectField("Start time hour", validators=[Optional()])
    start_time_minute = SelectField("Start time minute", validators=[Optional()])
    end_time_hour = SelectField("End time hour", validators=[Optional()])
    end_time_minute = SelectField("End time minute", validators=[Optional()])
    staff_ids = SelectMultipleField(
        "Assigned staff",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    customer_notes = TextAreaField("Customer notes", validators=[Optional(), Length(max=2000)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Add Work")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initialize_time_selects()
        self.services_enabled = is_services_enabled()
        self.set_service_choices(selected_ids=self.service_ids.data)
        self.staff_ids.choices = _load_staff_choices()

    def set_service_choices(self, selected_ids: list[int] | None = None) -> None:
        self.service_ids.validate_choice = False
        if not self.services_enabled:
            self.service_ids.choices = []
            return
        self.service_ids.choices = _load_service_choices_with_selected(selected_ids)

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        return self.validate_time_selects() and valid


class ServiceManagementForm(FlaskForm):
    name = StringField("Service name", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Service")


class GalleryItemUploadForm(FlaskForm):
    image = FileField(
        "Image",
        validators=[
            FileRequired("Choose an image to upload."),
            FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only."),
        ],
    )
    title = StringField("Title", validators=[DataRequired(), Length(max=80)])
    caption = TextAreaField("Caption", validators=[Optional(), Length(max=180)])
    service_id = SelectField("Linked service", coerce=int, validators=[Optional()], default=0)
    featured = BooleanField("Featured", validators=[Optional()])
    submit = SubmitField("Upload Image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_id.validate_choice = False
        self.service_id.choices = _load_gallery_service_choices()


class GalleryItemEditForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=80)])
    caption = TextAreaField("Caption", validators=[Optional(), Length(max=180)])
    service_id = SelectField("Linked service", coerce=int, validators=[Optional()], default=0)
    featured = BooleanField("Featured", validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_id.validate_choice = False
        self.service_id.choices = _load_gallery_service_choices()


class RecurringWorkForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "start_time": {"label": "default start time"},
        "end_time": {"label": "default end time"},
    }

    title = HiddenField("Service title", validators=[Optional()])
    service_ids = SelectMultipleField(
        "Services",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    customer_id = HiddenField("Customer", validators=[Optional()])
    customer_lookup = StringField("Customer", validators=[Optional()])
    frequency = SelectField(
        "Preset",
        choices=[
            ("weekly", "Weekly"),
            ("biweekly", "Biweekly"),
            ("monthly", "Monthly"),
            ("semi_monthly", "Semi-monthly"),
            ("bimonthly", "Every 2 months"),
            ("custom", "Custom"),
        ],
        default="weekly",
        validators=[DataRequired()],
    )
    recurrence_unit = SelectField(
        "Repeat by",
        choices=[("week", "Week"), ("month", "Month")],
        default="week",
        validators=[DataRequired()],
    )
    recurrence_interval = IntegerField(
        "Repeat interval",
        default=1,
        validators=[Optional(), NumberRange(min=1, max=12)],
        render_kw={"min": "1", "max": "12", "step": "1", "inputmode": "numeric"},
    )
    weekdays = SelectMultipleField(
        "Weekdays",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    month_days = SelectMultipleField(
        "Month days",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    starts_on = DateField("Start date", validators=[DataRequired()])
    ends_on = DateField("End date", validators=[Optional()])
    start_time_hour = SelectField("Default start time hour", validators=[Optional()])
    start_time_minute = SelectField("Default start time minute", validators=[Optional()])
    end_time_hour = SelectField("Default end time hour", validators=[Optional()])
    end_time_minute = SelectField("Default end time minute", validators=[Optional()])
    billing_amount = DecimalField(
        "Billing amount",
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"step": "0.01", "min": "0", "inputmode": "decimal"},
    )
    billing_frequency = SelectField(
        "Billing frequency",
        choices=[("", "None"), *[(frequency, frequency.replace("_", " ").capitalize()) for frequency in RecurringWork.BILLING_FREQUENCIES]],
        validators=[Optional()],
    )
    status = SelectField(
        "Status",
        choices=[(status, status.capitalize()) for status in RecurringWork.STATUSES],
        default="active",
        validators=[DataRequired()],
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Recurring Work")

    def __init__(self, *args, **kwargs):
        source = kwargs.get("obj")
        super().__init__(*args, **kwargs)
        selected_title = (getattr(source, "title", None) or "").strip() or None
        self.title.choices = _load_recurring_work_service_choices(selected_title=selected_title)
        selected_service_ids = _resolve_recurring_work_service_ids_for_title(selected_title)
        self.service_ids.validate_choice = False
        self.service_ids.choices = _load_service_choices_with_selected(selected_service_ids)
        self.service_ids.data = selected_service_ids
        self.customer_id.data = getattr(source, "customer_id", None)
        if getattr(source, "customer", None) is not None:
            self.customer_lookup.data = getattr(source.customer, "primary_name", "") or ""
        self.weekdays.choices = [(index, day) for index, day in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])]
        self.month_days.choices = [(day, str(day)) for day in range(1, 32)]

        schedule_defaults = _resolve_recurring_work_form_schedule_defaults(source)
        if selected_title and not self.title.data:
            self.title.data = selected_title
        if self.frequency.data in (None, ""):
            self.frequency.data = str(schedule_defaults["frequency"])
        if self.recurrence_unit.data in (None, ""):
            self.recurrence_unit.data = str(schedule_defaults["unit"])
        if self.recurrence_interval.data in (None, ""):
            self.recurrence_interval.data = int(schedule_defaults["interval"])
        if not self.weekdays.data:
            self.weekdays.data = list(schedule_defaults["weekdays"])
        if not self.month_days.data:
            self.month_days.data = list(schedule_defaults["month_days"])
        self._initialize_time_selects(source=source)

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        has_billing_amount = self.billing_amount.data not in (None, "")
        has_billing_frequency = bool((self.billing_frequency.data or "").strip())

        if has_billing_amount and not has_billing_frequency:
            self.billing_frequency.errors.append("Choose a billing frequency.")
            valid = False
        if has_billing_frequency and not has_billing_amount:
            self.billing_amount.errors.append("Enter a billing amount.")
            valid = False

        if self.service_ids.data:
            services = ServiceOption.query.filter(ServiceOption.id.in_(self.service_ids.data)).order_by(ServiceOption.display_order.asc(), ServiceOption.name.asc()).all()
            self.title.data = ", ".join([service.name for service in services])
        elif self.title.data:
            resolved_service_ids = _resolve_recurring_work_service_ids_for_title(self.title.data)
            self.service_ids.data = resolved_service_ids
            if resolved_service_ids:
                services = ServiceOption.query.filter(ServiceOption.id.in_(resolved_service_ids)).order_by(ServiceOption.display_order.asc(), ServiceOption.name.asc()).all()
                self.title.data = ", ".join([service.name for service in services])

        if not self.service_ids.data and not self.title.data:
            self.service_ids.errors.append("Choose at least one service.")
            valid = False

        return self.validate_time_selects() and valid


class RecurringWorkGenerationForm(FlaskForm):
    days_ahead = SelectField(
        "Keep synced for",
        choices=[("30", "Next 30 days"), ("60", "Next 60 days")],
        default="60",
        validators=[DataRequired()],
    )
    submit = SubmitField("Update synced window")


class AppointmentForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "start_time": {"label": "start time"},
        "end_time": {"label": "end time"},
        "requested_time": {"label": "requested time"},
        "confirmed_time": {"label": "confirmed time"},
    }

    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    customer_lookup = StringField("Customer", validators=[Optional()])
    title = StringField("Work title / summary", validators=[Optional(), Length(max=255)])
    staff_ids = SelectMultipleField(
        "Assigned staff",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    scheduled_date = DateField("Scheduled date", validators=[Optional()])
    start_time_hour = SelectField("Start time hour", validators=[Optional()])
    start_time_minute = SelectField("Start time minute", validators=[Optional()])
    end_time_hour = SelectField("End time hour", validators=[Optional()])
    end_time_minute = SelectField("End time minute", validators=[Optional()])
    customer_notes = TextAreaField("Customer notes", validators=[Optional(), Length(max=2000)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_hour = SelectField("Requested time hour", validators=[Optional()])
    requested_time_minute = SelectField("Requested time minute", validators=[Optional()])
    confirmed_date = DateField("Confirmed date", validators=[Optional()])
    confirmed_time_hour = SelectField("Confirmed time hour", validators=[Optional()])
    confirmed_time_minute = SelectField("Confirmed time minute", validators=[Optional()])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        source = kwargs.get("obj")
        super().__init__(*args, **kwargs)
        self._initialize_time_selects(source=source)
        from app.models import Customer

        customers = Customer.query.order_by(Customer.primary_name, Customer.id).all()
        self.customer_id.choices = [
            (0, "Choose an existing customer"),
            *[
                (
                    customer.id,
                    f"{customer.primary_name or 'Unnamed'} — {customer.primary_email or 'no email'} — {customer.primary_phone or 'no phone'}",
                )
                for customer in customers
            ],
        ]
        self.staff_ids.choices = _load_staff_choices()

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        return self.validate_time_selects() and valid


class RescheduleAppointmentForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "start_time": {"label": "start time"},
        "end_time": {"label": "end time"},
        "requested_time": {"label": "requested time"},
    }

    scheduled_date = DateField("Scheduled date", validators=[Optional()])
    start_time_hour = SelectField("Start time hour", validators=[Optional()])
    start_time_minute = SelectField("Start time minute", validators=[Optional()])
    end_time_hour = SelectField("End time hour", validators=[Optional()])
    end_time_minute = SelectField("End time minute", validators=[Optional()])
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_hour = SelectField("Requested time hour", validators=[Optional()])
    requested_time_minute = SelectField("Requested time minute", validators=[Optional()])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        source = kwargs.get("obj")
        super().__init__(*args, **kwargs)
        self._initialize_time_selects(source=source)

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        return self.validate_time_selects() and valid


class AppointmentStatusForm(FlaskForm):
    status = SelectField(
        "Appointment status",
        choices=[(status, status) for status in APPOINTMENT_STATUSES],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update Status")

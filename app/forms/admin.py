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

    title = StringField("Service or work title", validators=[DataRequired(), Length(max=255)])
    frequency = SelectField(
        "Frequency",
        choices=[(frequency, frequency.capitalize()) for frequency in RecurringWork.FREQUENCIES],
        default="weekly",
        validators=[DataRequired()],
    )
    day_of_week = SelectField(
        "Weekly day",
        choices=[(-1, "Choose a weekday"), *[(index, day) for index, day in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])]],
        coerce=int,
        default=-1,
        validators=[Optional()],
    )
    day_of_month = SelectField(
        "Monthly day",
        choices=[(0, "Choose a day of month"), *[(day, str(day)) for day in range(1, 32)]],
        coerce=int,
        default=0,
        validators=[Optional()],
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

        return self.validate_time_selects() and valid


class RecurringWorkGenerationForm(FlaskForm):
    days_ahead = SelectField(
        "Generate for",
        choices=[("30", "Next 30 days"), ("60", "Next 60 days")],
        default="60",
        validators=[DataRequired()],
    )
    submit = SubmitField("Generate Upcoming Appointments")


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

from app.models import APPOINTMENT_STATUSES, RecurringWork, RequestQuote, ServiceOption, StaffMember
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from wtforms import BooleanField, DateField, DecimalField, HiddenField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, NumberRange, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.forms.time_selects import TimeSelectMixin


class CheckboxInputWithoutRequired(CheckboxInput):
    validation_attrs = ["disabled"]


def _load_service_choices() -> list[tuple[int, str]]:
    options = ServiceOption.query.order_by(ServiceOption.name).all()
    return [(option.id, option.name) for option in options]


def _load_staff_choices() -> list[tuple[int, str]]:
    from app.models import StaffMember

    staff_members = StaffMember.query.order_by(StaffMember.display_name).all()
    return [(staff.id, staff.display_name) for staff in staff_members]


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
    primary_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    primary_phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    primary_email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    primary_city = StringField("City", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save Customer")


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
        self.services.choices = _load_service_choices()

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
<<<<<<< HEAD
=======
    title = StringField("Work title / summary", validators=[DataRequired(), Length(max=255)])
    service_ids = SelectMultipleField(
        "Services",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
>>>>>>> 7c44e41e837bd82372ab5a71aabd4bec807d88df
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
        self.service_ids.choices = _load_service_choices()
        self.staff_ids.choices = _load_staff_choices()

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        return self.validate_time_selects() and valid


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
<<<<<<< HEAD
=======
    title = StringField("Work title / summary", validators=[Optional(), Length(max=255)])
    staff_ids = SelectMultipleField(
        "Assigned staff",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
>>>>>>> 7c44e41e837bd82372ab5a71aabd4bec807d88df
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

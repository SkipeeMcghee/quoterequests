from app.models import APPOINTMENT_STATUSES, QUOTE_REQUEST_STATUSES, ServiceOption
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from wtforms import BooleanField, DateField, DecimalField, HiddenField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional
from wtforms.widgets import CheckboxInput, ListWidget


class CheckboxInputWithoutRequired(CheckboxInput):
    validation_attrs = ["disabled"]


class StatusUpdateForm(FlaskForm):
    status = SelectField(
        "Status",
        choices=[(status, status) for status in QUOTE_REQUEST_STATUSES],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update Status")


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
    manual_customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    submit = SubmitField("Link Customer")


class CreateCustomerForm(FlaskForm):
    submit = SubmitField("Add Customer")


class CustomerInfoForm(FlaskForm):
    primary_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    primary_phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    primary_email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    primary_city = StringField("City", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save Changes")


class CustomerAddressForm(FlaskForm):
    address_line_1 = StringField("Address Line 1", validators=[Optional(), Length(max=255)])
    address_line_2 = StringField("Address Line 2", validators=[Optional(), Length(max=255)])
    state = StringField("State", validators=[Optional(), Length(max=255)])
    zip_code = StringField("Zip", validators=[Optional(), Length(max=20)])
    is_billing = BooleanField("Mark as billing address", validators=[Optional()])
    submit = SubmitField("Save Changes")


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
    submit = SubmitField("Add Alternate Value")


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
    submit = SubmitField("Save Changes")


class CustomerNoteForm(FlaskForm):
    note_text = TextAreaField("Customer note", validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField("Save Changes")


class MergeCustomerForm(FlaskForm):
    target_customer_id = SelectField("Surviving customer", coerce=int, validators=[DataRequired()])
    confirm = BooleanField("I understand this will merge the source customer into the selected target", validators=[DataRequired()])
    submit = SubmitField("Merge Customer")


class StaffMemberForm(FlaskForm):
    display_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    role_title = StringField("Role / title", validators=[Optional(), Length(max=120)])
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
    services = SelectMultipleField(
        "Services",
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services.choices = self._load_service_choices()

    def _load_service_choices(self) -> list[tuple[int, str]]:
        options = ServiceOption.query.order_by(ServiceOption.name).all()
        return [(option.id, option.name) for option in options]


class AppointmentStaffAssignmentForm(FlaskForm):
    staff_ids = SelectMultipleField("Assigned staff", coerce=int, validators=[Optional()])
    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_ids.choices = self._load_staff_choices()

    def _load_staff_choices(self) -> list[tuple[int, str]]:
        from app.models import StaffMember

        staff_members = StaffMember.query.order_by(StaffMember.display_name).all()
        return [(staff.id, staff.display_name) for staff in staff_members]


class StaffAvailabilityForm(FlaskForm):
    day_of_week = SelectField(
        "Day of week",
        choices=[(str(i), day) for i, day in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])],
        coerce=int,
        validators=[DataRequired()],
    )
    start_time = TimeField("Start time", validators=[DataRequired()])
    end_time = TimeField("End time", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")


class CreateScheduledWorkForm(FlaskForm):
    request_id = HiddenField()
    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    new_customer_name = StringField("New customer name", validators=[Optional(), Length(max=255)])
    new_customer_phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    new_customer_email = StringField("Email", validators=[Optional(), Length(max=255), Email()])
    new_customer_city = StringField("City", validators=[Optional(), Length(max=255)])
    title = StringField("Work title / summary", validators=[DataRequired(), Length(max=255)])
    scheduled_date = DateField("Scheduled date", validators=[DataRequired()])
    start_time = TimeField("Start time", validators=[Optional()])
    end_time = TimeField("End time", validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[(status, status) for status in ("Scheduled", "Requested", "Completed", "Cancelled", "Rescheduled", "No Show")],
        default="Scheduled",
        validators=[DataRequired()],
    )
    customer_notes = TextAreaField("Customer notes", validators=[Optional(), Length(max=2000)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Add Work")


class RecurringWorkGenerationForm(FlaskForm):
    days_ahead = SelectField(
        "Generate for",
        choices=[("30", "Next 30 days"), ("60", "Next 60 days")],
        default="60",
        validators=[DataRequired()],
    )
    submit = SubmitField("Generate Appointments")


class AppointmentForm(FlaskForm):
    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    title = StringField("Work title / summary", validators=[Optional(), Length(max=255)])
    scheduled_date = DateField("Scheduled date", validators=[Optional()])
    start_time = TimeField("Start time", validators=[Optional()])
    end_time = TimeField("End time", validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[(status, status) for status in ("Scheduled", "Completed", "Cancelled", "Rescheduled", "No Show")],
        default="Scheduled",
        validators=[DataRequired()],
    )
    customer_notes = TextAreaField("Customer notes", validators=[Optional(), Length(max=2000)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_window = StringField("Requested time window", validators=[Optional(), Length(max=120)])
    confirmed_date = DateField("Confirmed date", validators=[Optional()])
    confirmed_time_window = StringField("Confirmed time window", validators=[Optional(), Length(max=120)])
    submit = SubmitField("Save Changes")


class RescheduleAppointmentForm(FlaskForm):
    scheduled_date = DateField("Scheduled date", validators=[Optional()])
    start_time = TimeField("Start time", validators=[Optional()])
    end_time = TimeField("End time", validators=[Optional()])
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_window = StringField("Time window", validators=[Optional(), Length(max=120)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Changes")


class AppointmentStatusForm(FlaskForm):
    status = SelectField(
        "Appointment status",
        choices=[(status, status) for status in APPOINTMENT_STATUSES],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update Status")

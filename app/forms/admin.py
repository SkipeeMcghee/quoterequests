from app.models import APPOINTMENT_STATUSES, QUOTE_REQUEST_STATUSES
from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, DecimalField, HiddenField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class StatusUpdateForm(FlaskForm):
    status = SelectField(
        "Status",
        choices=[(status, status) for status in QUOTE_REQUEST_STATUSES],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update status")


class NoteForm(FlaskForm):
    note_text = TextAreaField("Internal note", validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField("Save note")


class DeleteNoteForm(FlaskForm):
    submit = SubmitField("Delete")


class LastContactedForm(FlaskForm):
    last_contacted_on = DateField("Last contacted on", validators=[Optional()])
    submit = SubmitField("Save last contact")


class LinkCustomerForm(FlaskForm):
    customer_id = HiddenField("Customer ID", validators=[DataRequired()])
    submit = SubmitField("Link customer")


class CreateCustomerForm(FlaskForm):
    submit = SubmitField("Create customer")


class CustomerFieldForm(FlaskForm):
    kind = SelectField(
        "Field type",
        choices=[("name", "Name"), ("phone", "Phone"), ("email", "Email"), ("city", "City")],
        validators=[DataRequired()],
    )
    value = StringField("Value", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Add alternate value")


class SetPrimaryFieldForm(FlaskForm):
    field_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Make primary")


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
    submit = SubmitField("Save billing")


class CustomerNoteForm(FlaskForm):
    note_text = TextAreaField("Customer note", validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField("Save note")


class MergeCustomerForm(FlaskForm):
    target_customer_id = SelectField("Surviving customer", coerce=int, validators=[DataRequired()])
    confirm = BooleanField("I understand this will merge the source customer into the selected target", validators=[DataRequired()])
    submit = SubmitField("Merge customer")


class RecurringWorkGenerationForm(FlaskForm):
    days_ahead = SelectField(
        "Generate for",
        choices=[("30", "Next 30 days"), ("60", "Next 60 days")],
        default="60",
        validators=[DataRequired()],
    )
    submit = SubmitField("Generate recurring appointments")


class AppointmentForm(FlaskForm):
    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
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
    submit = SubmitField("Save appointment")


class RescheduleAppointmentForm(FlaskForm):
    scheduled_date = DateField("Scheduled date", validators=[Optional()])
    start_time = TimeField("Start time", validators=[Optional()])
    end_time = TimeField("End time", validators=[Optional()])
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_window = StringField("Time window", validators=[Optional(), Length(max=120)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Reschedule appointment")


class AppointmentStatusForm(FlaskForm):
    status = SelectField(
        "Appointment status",
        choices=[(status, status) for status in APPOINTMENT_STATUSES],
        validators=[DataRequired()],
    )
    submit = SubmitField("Update status")

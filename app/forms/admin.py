from app.models import APPOINTMENT_STATUSES, QUOTE_REQUEST_STATUSES
from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


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


class AppointmentForm(FlaskForm):
    requested_date = DateField("Requested date", validators=[Optional()])
    requested_time_window = StringField("Requested time window", validators=[Optional(), Length(max=120)])
    confirmed_date = DateField("Confirmed date", validators=[Optional()])
    confirmed_time_window = StringField("Confirmed time window", validators=[Optional(), Length(max=120)])
    customer_notes = TextAreaField("Customer notes", validators=[Optional(), Length(max=2000)])
    internal_notes = TextAreaField("Internal notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save appointment")


class RescheduleAppointmentForm(FlaskForm):
    requested_date = DateField("Reschedule date", validators=[Optional()])
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

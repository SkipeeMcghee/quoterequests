from app.models import QUOTE_REQUEST_STATUSES
from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


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
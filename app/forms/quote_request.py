from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from wtforms import EmailField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


PREFERRED_CONTACT_CHOICES = [
    ("Phone", "Phone"),
    ("Email", "Email"),
    ("Text", "Text"),
]


class QuoteRequestForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=50)])
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    service_type = StringField("Service type", validators=[DataRequired(), Length(max=120)])
    address = StringField("Address", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Project details", validators=[DataRequired(), Length(max=4000)])
    preferred_contact_method = SelectField(
        "Preferred contact method",
        choices=PREFERRED_CONTACT_CHOICES,
        validators=[DataRequired()],
    )
    preferred_contact_time = StringField("Preferred contact time", validators=[Optional(), Length(max=120)])
    photos = MultipleFileField(
        "Project photos",
        validators=[FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")],
    )
    submit = SubmitField("Send request")
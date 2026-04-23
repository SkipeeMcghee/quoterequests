from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from sqlalchemy.exc import SQLAlchemyError
from wtforms import DateField, EmailField, ValidationError, SelectMultipleField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.extensions import db
from app.models import ServiceOption


class CheckboxInputWithoutRequired(CheckboxInput):
    validation_attrs = ["disabled"]


SERVICE_CHOICES = [
    ("Landscape Design", "Landscape Design"),
    ("Roof Repair", "Roof Repair"),
    ("Window Cleaning", "Window Cleaning"),
    ("Inspection", "Inspection"),
    ("Painting", "Painting"),
    ("Deck Staining", "Deck Staining"),
    ("Flooring", "Flooring"),
    ("Siding", "Siding"),
    ("Fence Repair", "Fence Repair"),
    ("General Maintenance", "General Maintenance"),
]


class QuoteRequestForm(FlaskForm):
    full_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    contact_information = StringField("Contact Information", validators=[DataRequired(), Length(max=255)])
    city = StringField("Location", validators=[DataRequired(), Length(max=255)])
    preferred_date = DateField("Preferred date", validators=[Optional()])
    preferred_time_window = StringField("Preferred time window", validators=[Optional(), Length(max=120)])
    scheduling_notes = TextAreaField("Scheduling notes", validators=[Optional(), Length(max=2000)])
    services = SelectMultipleField(
        "Services",
        choices=[],
        validators=[DataRequired()],
        validate_choice=False,
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    photos = MultipleFileField(
        "Project photos",
        validators=[FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")],
    )
    submit = SubmitField("Send request")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services.choices = self._load_service_choices()

    def _load_service_choices(self) -> list[tuple[str, str]]:
        try:
            options = ServiceOption.query.order_by(ServiceOption.name).all()
            if options:
                return [(option.name, option.name) for option in options]
        except SQLAlchemyError:
            db.session.rollback()

        return SERVICE_CHOICES

    def validate(self, extra_validators=None) -> bool:
        valid = super().validate(extra_validators=extra_validators)
        if not valid:
            return False

        contact = (self.contact_information.data or "").strip()
        if not contact:
            self.contact_information.errors.append("Provide a phone number or email address.")
            return False

        if "@" in contact:
            try:
                Email()(self, self.contact_information)
            except ValidationError as exc:
                self.contact_information.errors.append(str(exc))
                return False

        return True
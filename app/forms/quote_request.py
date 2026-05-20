from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from wtforms import DateField, EmailField, HiddenField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField, ValidationError
from wtforms.validators import DataRequired, Email, Length, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.forms.time_selects import TimeSelectMixin
from app.services.service_catalog import is_services_enabled, list_service_name_choices


class CheckboxInputWithoutRequired(CheckboxInput):
    validation_attrs = ["disabled"]


class QuoteRequestForm(TimeSelectMixin, FlaskForm):
    TIME_FIELD_CONFIG = {
        "preferred_time": {"label": "preferred time"},
    }

    full_name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    email = EmailField("Email", validators=[Optional(), Length(max=255)])
    city = StringField("Location", validators=[DataRequired(), Length(max=255)])
    preferred_date = DateField("Preferred date", validators=[Optional()])
    preferred_time_hour = SelectField("Preferred time hour", validators=[Optional()])
    preferred_time_minute = SelectField("Preferred time minute", validators=[Optional()])
    additional_notes = TextAreaField(
        "Additional Notes",
        validators=[Optional(), Length(max=2000)],
        render_kw={"placeholder": "Optional", "rows": 1},
    )
    services = SelectMultipleField(
        "Services",
        choices=[],
        validators=[DataRequired()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInputWithoutRequired(),
    )
    photos = MultipleFileField(
        "Project photos",
        validators=[FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")],
    )
    recaptcha_token = HiddenField("reCAPTCHA token", validators=[Optional()])
    submit = SubmitField("Send Request")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initialize_time_selects()
        self.services_enabled = is_services_enabled()
        self._configure_services_field()

    def _configure_services_field(self) -> None:
        self.services.validate_choice = False
        if self.services_enabled:
            self.services.validators = [DataRequired()]
            self.services.choices = self._load_service_choices()
            return

        self.services.validators = [Optional()]
        self.services.choices = []
        self.services.data = []

    def _load_service_choices(self) -> list[tuple[str, str]]:
        return list_service_name_choices(include_inactive=False)

    def validate(self, extra_validators=None) -> bool:
        if not self.services_enabled:
            self.services.data = []

        valid = super().validate(extra_validators=extra_validators)
        time_valid = self.validate_time_selects()
        if not valid or not time_valid:
            return False

        if self.photos.data and len(self.photos.data) > 20:
            self.photos.errors.append("You can upload up to 20 photos.")
            return False

        phone = (self.phone.data or "").strip()
        email = (self.email.data or "").strip()
        if not phone and not email:
            self.phone.errors.append("Provide a phone number or email address.")
            return False

        if email:
            try:
                Email()(self, self.email)
            except ValidationError as exc:
                self.email.errors.append(str(exc))
                return False

        return True
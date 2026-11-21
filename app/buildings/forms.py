from datetime import date

from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional, Regexp, StopValidation, ValidationError
from wtforms.widgets import HiddenInput


def strip(value):
    return value.strip() if value else value


def finite(form, field):
    if field.data is not None and not field.data.is_finite():
        raise StopValidation("Enter a finite number.")


class BuildingForm(FlaskForm):
    code = StringField("Building ID", filters=[strip], validators=[InputRequired(), Length(max=60), Regexp(r"^[A-Za-z0-9_-]+$", message="Use letters, numbers, hyphens or underscores.")])
    name = StringField("Building name", filters=[strip], validators=[InputRequired(), Length(min=1, max=160)])
    ward_id = SelectField("Ward", coerce=int, validators=[InputRequired()])
    address = StringField("Location / address", filters=[strip], validators=[Optional(), Length(max=255)])
    latitude = DecimalField("Latitude", places=6, validators=[Optional(), finite, NumberRange(-90, 90)])
    longitude = DecimalField("Longitude", places=6, validators=[Optional(), finite, NumberRange(-180, 180)])
    building_use = SelectField("Building use", choices=[(v, v.capitalize()) for v in ("unknown", "residential", "school", "office", "community", "commercial", "industrial", "other")])
    construction_year = IntegerField("Construction year", validators=[Optional(), NumberRange(1000, 9999)])
    occupied_floors = IntegerField("Occupied floors", validators=[Optional(), NumberRange(0, 32767)])
    ground_contact_rooms = IntegerField("Ground-contact rooms", validators=[Optional(), NumberRange(0, 32767)])
    ventilation = SelectField("Ventilation", choices=[(v, v.capitalize()) for v in ("unknown", "natural", "mechanical", "mixed")])
    approximate_occupancy = IntegerField("Approximate occupancy", validators=[Optional(), NumberRange(0, 2147483647)])
    hours_of_use_per_day = DecimalField("Hours of use per day", places=2, validators=[Optional(), finite, NumberRange(0, 24)])
    private_notes = TextAreaField("Officer-only notes", filters=[strip], validators=[Optional(), Length(max=5000)])
    is_synthetic = BooleanField("This is a fictional / synthetic building record")
    version_id = IntegerField(widget=HiddenInput(), default=1, validators=[InputRequired(), NumberRange(1)])
    change_reason = TextAreaField("Reason for this change", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])
    submit = SubmitField("Save building")

    def validate_construction_year(self, field):
        if field.data and field.data > date.today().year:
            raise ValidationError("Construction year cannot be in the future.")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if (self.latitude.data is None) != (self.longitude.data is None):
            self.longitude.errors = list(self.longitude.errors) + ["Enter both coordinates, or leave both blank for unknown."]
            valid = False
        return valid


class AssignmentForm(FlaskForm):
    responsible_officer_id = SelectField("Responsible officer", coerce=int)
    next_action = TextAreaField("Next action", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])
    reason = TextAreaField("Reason for assignment update", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])
    submit = SubmitField("Update assignment")

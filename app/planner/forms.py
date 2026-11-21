from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, DateTimeLocalField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional, Regexp, ValidationError


def strip(value):
    return value.strip() if value else value


class CampaignForm(FlaskForm):
    code = StringField("Campaign ID", filters=[strip], validators=[InputRequired(), Length(max=80), Regexp(r"^[A-Za-z0-9_.-]+$", message="Use letters, numbers, dots, hyphens or underscores.")])
    name = StringField("Campaign name", filters=[strip], validators=[InputRequired(), Length(max=160)])
    track = SelectField("Assessment track", choices=[("indoor_radon", "Indoor radon"), ("regional_radiation", "Regional radiation")])
    starts_on = DateField("Start date", validators=[InputRequired()])
    ends_on = DateField("End date", validators=[InputRequired()])
    available_slots = IntegerField("Nominal assessment slots", validators=[InputRequired(), NumberRange(min=0, max=100000)])
    staff_slots = IntegerField("Staff-limited slots, if known", validators=[Optional(), NumberRange(min=0, max=100000)])
    equipment_slots = IntegerField("Equipment-limited slots, if known", validators=[Optional(), NumberRange(min=0, max=100000)])
    follow_up_weight = IntegerField("Required follow-up policy value (recorded; follow-ups always come first)", default=3, validators=[InputRequired(), NumberRange(min=0, max=1000)])
    priority_weight = IntegerField("Priority screening planning weight", default=5, validators=[InputRequired(), NumberRange(min=0, max=1000)])
    coverage_weight = IntegerField("Coverage-gap planning weight", default=2, validators=[InputRequired(), NumberRange(min=0, max=1000)])
    notes = TextAreaField("Planning notes", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    reason = TextAreaField("Reason for creating this campaign", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])

    def validate_ends_on(self, field):
        if self.starts_on.data and field.data and field.data < self.starts_on.data:
            raise ValidationError("End date cannot be before start date.")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if valid and not any((self.follow_up_weight.data, self.priority_weight.data, self.coverage_weight.data)):
            self.follow_up_weight.errors.append("At least one planning weight must be above zero.")
            valid = False
        return valid


class CandidateForm(FlaskForm):
    case_id = SelectField("Eligible assessment case", coerce=int, validators=[InputRequired()])
    reason = TextAreaField("Reason for adding this candidate", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])


class GeneratePlanForm(FlaskForm):
    random_seed = IntegerField("Optional reproducible random seed", validators=[Optional(), NumberRange(min=0, max=9223372036854775807)])
    reason = TextAreaField("Reason for generating this plan", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])


class OverrideForm(FlaskForm):
    replacement_case_id = SelectField("Replacement candidate", coerce=int, validators=[InputRequired()])
    selection_order = SelectField("Replace this plan position", coerce=int, validators=[InputRequired()])
    reason = TextAreaField("Reason for officer override", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])


class BookingForm(FlaskForm):
    equipment_id = SelectField("Equipment", coerce=int, validators=[InputRequired()])
    case_id = SelectField("Assessment case", coerce=int, validators=[InputRequired()])
    starts_at = DateTimeLocalField("Booking starts (UTC)", format="%Y-%m-%dT%H:%M", validators=[InputRequired()])
    ends_at = DateTimeLocalField("Booking ends (UTC)", format="%Y-%m-%dT%H:%M", validators=[InputRequired()])
    notes = TextAreaField("Booking notes", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    reason = TextAreaField("Reason for booking", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])

    def validate_ends_at(self, field):
        if self.starts_at.data and field.data and field.data <= self.starts_at.data:
            raise ValidationError("Booking end must be later than its start.")

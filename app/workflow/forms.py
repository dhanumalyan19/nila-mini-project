from datetime import datetime

from flask_wtf import FlaskForm
from wtforms import DateTimeLocalField, DecimalField, SelectField, StringField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional, Regexp, ValidationError


def strip(value):
    return value.strip() if value else value


class MeasurementEntryForm(FlaskForm):
    record_key = StringField("Measurement record ID", filters=[strip], validators=[InputRequired(), Length(max=100), Regexp(r"^[A-Za-z0-9_.-]+$", message="Use letters, numbers, dots, hyphens or underscores.")])
    building_id = SelectField("Building", coerce=int, validators=[InputRequired()])
    kind = SelectField("Track, measurement type and unit", validators=[InputRequired()])
    value = DecimalField("Measured value", places=6, validators=[InputRequired(), NumberRange(min=0)])
    started_at = DateTimeLocalField("Measurement started (UTC)", format="%Y-%m-%dT%H:%M", validators=[InputRequired()])
    ended_at = DateTimeLocalField("Measurement ended (UTC)", format="%Y-%m-%dT%H:%M", validators=[InputRequired()])
    instrument = StringField("Instrument", filters=[strip], validators=[InputRequired(), Length(max=160)])
    source = StringField("Source", filters=[strip], validators=[InputRequired(), Length(max=255)])
    notes = TextAreaField("Measurement notes", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    reason = TextAreaField("Reason for entering this measurement", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])

    def validate_ended_at(self, field):
        if self.started_at.data and field.data and field.data <= self.started_at.data:
            raise ValidationError("Measurement end must be later than its start.")


class MeasurementReviewForm(FlaskForm):
    decision = SelectField("Record-quality decision", choices=[("accepted", "Accepted"), ("needs_information", "Needs information"), ("rejected", "Rejected")], validators=[InputRequired()])
    rationale = TextAreaField("Review rationale", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])


class ActionForm(FlaskForm):
    case_id = SelectField("Assessment case", coerce=int, validators=[InputRequired()])
    guidance_entry_id = SelectField("Guidance reference (optional)", coerce=int, validators=[Optional()])
    assigned_to_id = SelectField("Responsible officer", coerce=int, validators=[InputRequired()])
    description = TextAreaField("Action to arrange", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    due_at = DateTimeLocalField("Due by (UTC, optional)", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    reason = TextAreaField("Reason for assigning this action", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])


class CompletionForm(FlaskForm):
    completion_notes = TextAreaField("Reported completion details", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    reason = TextAreaField("Reason for recording this update", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])


class FollowUpForm(FlaskForm):
    measurement_id = SelectField("Follow-up measurement evidence", coerce=int, validators=[InputRequired()])
    decision = SelectField("Reviewer decision", choices=[("more_evidence_needed", "More evidence needed"), ("further_action_required", "Further action required"), ("outcome_reviewed", "Outcome reviewed")], validators=[InputRequired()])
    evidence_notes = TextAreaField("Evidence reviewed", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])
    rationale = TextAreaField("Reviewer rationale", filters=[strip], validators=[InputRequired(), Length(min=1, max=4000)])


class RequestStatusForm(FlaskForm):
    status = SelectField("Request status", choices=[("submitted", "Submitted"), ("under_review", "Under review"), ("assigned", "Assigned"), ("closed", "Closed")], validators=[InputRequired()])
    reason = TextAreaField("Reason for status update", filters=[strip], validators=[InputRequired(), Length(min=1, max=2000)])

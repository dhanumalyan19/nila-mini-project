from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import BooleanField, SelectField, TextAreaField
from wtforms.validators import DataRequired, Length


class UploadForm(FlaskForm):
    kind = SelectField("Import type", choices=[("measurements", "Measurements — CSV"), ("areas", "Survey areas — GeoJSON"), ("locations", "Survey locations — CSV")])
    upload = FileField("File to preview", validators=[FileRequired()])


class CommitForm(FlaskForm):
    confirm = BooleanField("I checked the preview and want to save only its valid records.", validators=[DataRequired(message="Confirm that you checked the preview.")])
    reason = TextAreaField("Reason for importing", filters=[lambda value: value.strip() if value else value], validators=[DataRequired(), Length(min=1, max=1000)])
